import asyncio

import pytest

from org_harness.storage import BudgetExceeded, ConflictError, MemoryStorage, PostgresStorage


@pytest.fixture
async def storage():
    value = MemoryStorage()
    yield value


@pytest.mark.asyncio
async def test_create_and_commands_are_idempotent(storage):
    first = await storage.create_run({"user_request": "Build something"}, "create")
    same = await storage.create_run({"user_request": "Build something"}, "create")
    assert first == same
    with pytest.raises(ConflictError):
        await storage.create_run({"user_request": "Different"}, "create")
    paused = await storage.command(first["run_id"], "pause", {}, "pause")
    assert paused["status"] == "paused"
    assert await storage.command(first["run_id"], "pause", {}, "pause") == paused
    with pytest.raises(ConflictError):
        await storage.command(first["run_id"], "cancel", {}, "pause")
    await storage.command(first["run_id"], "cancel", {})
    with pytest.raises(ConflictError):
        await storage.command(first["run_id"], "resume", {"action": "continue"})


async def test_atomic_budgets_cannot_overspend(storage):
    run = await storage.create_run({"user_request": "test", "limits": {"max_model_calls": 2}})
    results = await asyncio.gather(
        *(storage.reserve_budget(run["run_id"], "model") for _ in range(8)), return_exceptions=True
    )
    assert sum(isinstance(value, BudgetExceeded) for value in results) == 6
    assert (await storage.get_run(run["run_id"]))["model_calls"] == 2


async def test_event_projection_cursor_and_source_deduplication(storage):
    event = {
        "source": "external",
        "event_id": "one",
        "agent_id": "backend_coder",
        "activity": "writing",
        "summary": "External writing",
    }
    first = await storage.emit(event)
    assert await storage.emit(event) == first
    await storage.emit({**event, "source": "harness", "summary": "Internal writing"})
    snapshot = await storage.office_snapshot()
    assert snapshot["cursor"] == 2
    assert len(snapshot["agents"]) == 2
    assert len(await storage.events_after(1)) == 1
    assert await storage.events_after(snapshot["cursor"]) == []


async def test_lease_and_cancelled_run_never_reexecuted(storage):
    first = await storage.create_run({"user_request": "one"})
    second = await storage.create_run({"user_request": "two"})
    assert (await storage.claim_job("worker-one"))["run_id"] == first["run_id"]
    assert await storage.claim_job("worker-two") is None
    assert not await storage.heartbeat(first["run_id"], "wrong-owner")
    await storage.command(first["run_id"], "cancel", {})
    await storage.update_run(first["run_id"], status="succeeded")
    assert (await storage.get_run(first["run_id"]))["status"] == "cancelled"
    await storage.finish_job(first["run_id"], "worker-one")
    assert (await storage.claim_job("worker-two"))["run_id"] == second["run_id"]


async def test_uncertain_command_requires_exact_review_then_authorized_retry(storage):
    run = await storage.create_run({"user_request": "one"})
    run_id = run["run_id"]
    operation = await storage.begin_operation(run_id, "op", "command", {"command": "touch output"})
    assert operation["status"] == "pending"
    assert len(await storage.uncertain_operations(run_id)) == 1
    await storage.update_run(
        run_id,
        status="review",
        review={"kind": "unknown_operation", "interrupt_id": "review-one", "operation_id": "op"},
    )
    with pytest.raises(ConflictError):
        await storage.command(
            run_id, "resume", {"interrupt_id": "old", "action": "retry_operation"}
        )
    await storage.command(
        run_id, "resume", {"interrupt_id": "review-one", "action": "retry_operation"}
    )
    assert await storage.uncertain_operations(run_id) == []
    retried = await storage.begin_operation(run_id, "op", "command", {"command": "touch output"})
    assert retried["status"] == "pending"
    await storage.complete_operation("op", {"exit_code": 0})
    assert (await storage.get_operation("op"))["result"]["exit_code"] == 0
    assert await storage.uncertain_operations(run_id) == []


async def test_notes_consumed_at_matching_boundary_once(storage):
    run = await storage.create_run({"user_request": "one"})
    await storage.command(
        run["run_id"], "notes", {"agent_id": "backend_coder", "content": "Use Python"}
    )
    assert await storage.consume_notes(run["run_id"], "market_researcher") == []
    assert (await storage.consume_notes(run["run_id"], "backend_coder"))[0][
        "content"
    ] == "Use Python"
    assert await storage.consume_notes(run["run_id"], "backend_coder") == []


@pytest.mark.integration
async def test_postgres_transactions_and_recovery(postgres_url):
    url = postgres_url
    storage = PostgresStorage(url)
    await storage.open()
    try:
        await storage.migrate()
        assert await storage.ready()
        from uuid import uuid4

        source = f"test:{uuid4()}"
        event = {"event_id": "same", "source": source, "agent_id": "test", "activity": "reading"}
        values = await asyncio.gather(*(storage.emit(event) for _ in range(5)))
        assert len({value["seq"] for value in values}) == 1
        run = await storage.create_run(
            {"user_request": "postgres", "limits": {"max_model_calls": 1}}
        )
        values = await asyncio.gather(
            *(storage.reserve_budget(run["run_id"], "model") for _ in range(4)),
            return_exceptions=True,
        )
        assert sum(isinstance(value, BudgetExceeded) for value in values) == 3
        await storage.command(run["run_id"], "cancel", {})
    finally:
        await storage.close()
