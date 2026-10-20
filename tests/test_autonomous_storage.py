"""Durable wakeups must survive reopen and respect operator/lease fences."""

from datetime import UTC, datetime, timedelta

import pytest

from org_harness.autonomy import autonomous_mode, retry_delay
from org_harness.models import RunLimits
from org_harness.storage import ConflictError, MemoryStorage, PostgresStorage

UNLIMITED = {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}


@pytest.fixture(params=["memory", "postgres"])
def scheduler_instance(request):
    if request.param == "memory":
        return MemoryStorage()
    return PostgresStorage(request.getfixturevalue("postgres_url"))


@pytest.fixture
async def scheduler(scheduler_instance):
    storage = scheduler_instance
    await storage.open()
    if isinstance(storage, PostgresStorage):
        await storage.migrate()
    try:
        yield storage
    finally:
        await storage.close()


async def mission(storage, limits=None):
    return await storage.create_run(
        {
            "user_request": "Complete a long mission",
            "limits": limits or UNLIMITED,
            "constitution": {"mission_statement": "Preserve all requirements"},
        }
    )


def test_autonomy_requires_three_explicit_unlimited_caps():
    assert autonomous_mode(UNLIMITED)
    assert autonomous_mode(RunLimits(**UNLIMITED))
    assert not autonomous_mode({})
    for key in UNLIMITED:
        assert not autonomous_mode({k: v for k, v in UNLIMITED.items() if k != key})
        assert not autonomous_mode({**UNLIMITED, key: 1})
    assert [retry_delay(n) for n in [1, 2, 3, 1000000]] == [5, 10, 20, 300]


async def test_wakeup_survives_reopen_without_blocking_other_missions(scheduler):
    first = await mission(scheduler)
    run_id = first["run_id"]
    assert (await scheduler.claim_job("first"))["run_id"] == run_id
    scheduled = await scheduler.schedule_retry(
        run_id, "first", 86400, "Provider temporarily unavailable", autonomous_failures=1
    )
    assert scheduled["status"] == "queued" and scheduled["review"] is None
    assert scheduled["model_calls"] == scheduled["tool_calls"] == 0
    await scheduler.finish_job(run_id, "first")
    reopened = None
    if isinstance(scheduler, PostgresStorage):
        reopened = PostgresStorage(scheduler.pool.conninfo)
        await scheduler.close()
        await reopened.open()
        scheduler = reopened
    try:
        assert await scheduler.claim_job("second") is None
        assert (await scheduler.get_run(run_id))["next_attempt_at"] == scheduled["next_attempt_at"]
        other = await mission(scheduler)
        assert (await scheduler.claim_job("second"))["run_id"] == other["run_id"]
        await scheduler.update_run(other["run_id"], status="succeeded")
        await scheduler.finish_job(other["run_id"], "second")
        # Advance past a week-long interruption without sleeping in a test.
        await scheduler.update_run(
            run_id, next_attempt_at=(datetime.now(UTC) - timedelta(days=7)).isoformat()
        )
        resumed = await scheduler.claim_job("new-process")
        assert resumed["run_id"] == run_id and resumed["status"] == "running"
        assert resumed["continuation"]["reason"] == "Provider temporarily unavailable"
        assert resumed["limits"] == UNLIMITED
    finally:
        if reopened is not None:
            await reopened.close()


@pytest.mark.parametrize("command", ["pause", "cancel"])
@pytest.mark.parametrize("before", [True, False])
async def test_operator_control_wins_before_or_after_automatic_scheduling(
    scheduler, command, before
):
    run = await mission(scheduler)
    rid = run["run_id"]
    await scheduler.claim_job("owner")
    if before:
        await scheduler.command(rid, command, {})
    result = await scheduler.schedule_retry(rid, "owner", 5, "Continue from checkpoint")
    if not before:
        await scheduler.command(rid, command, {})
    await scheduler.finish_job(rid, "owner")
    current = await scheduler.get_run(rid)
    assert current["status"] == {"pause": "paused", "cancel": "cancelled"}[command]
    assert current["next_attempt_at"] is None
    assert await scheduler.claim_job("another-owner") is None
    if command == "pause":
        assert current["review"]["kind"] == "manual_pause"
        await scheduler.command(
            rid, "resume", {"interrupt_id": current["review"]["interrupt_id"], "action": "continue"}
        )
        assert (await scheduler.claim_job("another-owner"))["run_id"] == rid
    else:
        assert current["cancel_requested"] is True
        assert result["status"] == ("cancelled" if before else "queued")


async def test_scheduling_rejects_wrong_owner_and_changed_requirements(scheduler):
    run = await mission(scheduler)
    rid = run["run_id"]
    await scheduler.claim_job("owner")
    with pytest.raises(ConflictError, match="lease"):
        await scheduler.schedule_retry(rid, "intruder", 0, "Continue")
    with pytest.raises(ValueError, match="requirements"):
        await scheduler.schedule_retry(rid, "owner", 0, "Continue", constitution={})
    assert (await scheduler.get_run(rid))["constitution"] == run["constitution"]
    await scheduler.finish_job(rid, "owner")
    with pytest.raises(ConflictError, match="lease"):
        await scheduler.schedule_retry(rid, "owner", 0, "Continue")


async def test_healthy_continuation_yields_fairly_to_a_waiting_mission(scheduler):
    first = await mission(scheduler)
    await scheduler.claim_job("owner")
    waiting = await mission(scheduler)
    await scheduler.schedule_retry(first["run_id"], "owner", 0, "Saved healthy private work chunk")
    await scheduler.finish_job(first["run_id"], "owner")
    assert (await scheduler.claim_job("another"))["run_id"] == waiting["run_id"]


@pytest.mark.parametrize(
    "kind,limits,eligible",
    [
        ("blocked", UNLIMITED, True),
        ("direction", UNLIMITED, True),
        ("manual_pause", UNLIMITED, False),
        ("blocked", {"max_model_calls": None, "worker_model_calls": None}, False),
        ("blocked", {**UNLIMITED, "max_tool_calls": 200}, False),
    ],
)
async def test_old_reviews_are_adopted_only_by_explicit_autonomous_policy(
    scheduler, kind, limits, eligible
):
    run = await mission(scheduler, limits)
    rid = run["run_id"]
    await scheduler.update_run(
        rid, status="review", review={"kind": kind, "interrupt_id": "old-review"}
    )
    claimed = await scheduler.claim_job("upgraded-worker")
    assert bool(claimed) is eligible
    if eligible:
        assert claimed["review"]["interrupt_id"] == "old-review"
        assert claimed["recovered"] is True
