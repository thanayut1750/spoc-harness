"""Office projections follow durable task lifecycle, including unstarted children."""

import asyncio

import pytest
from psycopg import OperationalError
from test_agent_services import assignment
from test_async_subagents import host_for, real_services

from org_harness.async_subagents import task_agent_id
from org_harness.models import Constitution

UNLIMITED = {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}


async def projection(storage, run_id, task_id):
    snapshot = await storage.office_snapshot()
    actor = task_agent_id(run_id, task_id)
    return next(agent for agent in snapshot["agents"] if agent["agent_id"] == actor)


async def test_third_real_child_waits_for_capacity_and_cancel_projects_idle_before_child_start(
    tmp_path, monkeypatch
):
    started = 0
    both_started = asyncio.Event()

    async def provider(body):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.Event().wait()

    async with real_services(tmp_path, monkeypatch, provider, limits=UNLIMITED) as (
        services,
        storage,
        run,
        requests,
    ):
        kr, _ = assignment()
        host = host_for(services, kr)
        manager = services.async_subagents()
        tasks = [
            await manager.start(
                "engineering_head",
                host,
                f"start-{index}",
                f"Capability {index}",
                Constitution(),
                kr,
            )
            for index in range(3)
        ]
        await asyncio.wait_for(both_started.wait(), 5)
        waiting = await projection(storage, run["run_id"], tasks[2]["task_id"])
        assert waiting["activity"] == "waiting" and waiting["data"]["task_status"] == "queued"
        assert waiting["data"]["parent_agent_id"] == "engineering_head"
        assert waiting["data"]["model_parent"] == "tools_rd_lead"
        assert (await manager.check("engineering_head", host, kr, tasks[2]["task_id"]))[
            "status"
        ] == "queued"
        assert len(requests) == 2  # The third actual agent never acquires a model request.
        await manager.cancel("engineering_head", host, kr, tasks[2]["task_id"])
        cancelled = await projection(storage, run["run_id"], tasks[2]["task_id"])
        assert cancelled["activity"] == "idle"
        assert cancelled["data"]["task_status"] == "cancelled"
        assert cancelled["data"]["task_id"] == tasks[2]["task_id"]
        assert len(requests) == 2
        # Cancelling one queued actor does not replace either running sibling.
        for task in tasks[:2]:
            running = await projection(storage, run["run_id"], task["task_id"])
            assert running["activity"] in {"planning", "executing"}
            assert running["data"]["task_status"] == "running"
        history = await storage.event_history(
            run_id=run["run_id"], agent_id=cancelled["agent_id"], source="harness"
        )
        assert [event["activity"] for event in history["events"]] == ["idle", "waiting"]
        assert "PRIVATE_REASONING" not in str(history)


async def test_mission_cancel_before_child_creation_publishes_cancelled_actor(
    tmp_path, monkeypatch
):
    async def provider(body):
        pytest.fail("Cancelled task must never call the provider")

    async with real_services(tmp_path, monkeypatch, provider) as (services, storage, run, requests):
        kr, _ = assignment()
        host = host_for(services, kr)
        await storage.command(run["run_id"], "cancel", {})

        def forbidden_child(current):
            pytest.fail("Cancelled task must never create child services")

        monkeypatch.setattr(services, "_background_service", forbidden_child)
        manager = services.async_subagents()
        task = await manager.start(
            "engineering_head", host, "race", "Capability", Constitution(), kr
        )
        assert (await manager.join("engineering_head", host, kr))[0]["status"] == "cancelled"
        event = await projection(storage, run["run_id"], task["task_id"])
        assert event["activity"] == "idle" and event["data"]["task_status"] == "cancelled"
        assert not requests


async def test_restored_queued_task_keeps_identity_and_cancel_remains_idle(tmp_path, monkeypatch):
    async def provider(body):
        pytest.fail("Capacity is deliberately unavailable in this fixture")

    async with real_services(tmp_path, monkeypatch, provider) as (services, storage, run, _):
        kr, _ = assignment()
        host = host_for(services, kr)
        manager = services.async_subagents()
        manager.slots = asyncio.Semaphore(0)
        task = await manager.start(
            "engineering_head", host, "saved", "Saved capability", Constitution(), kr
        )
        await manager.close()
        current = await storage.get_run(run["run_id"])
        async with real_services(
            tmp_path,
            monkeypatch,
            provider,
            storage=storage,
            run=current,
            saver=services.agent_checkpointer,
        ) as (fresh, _, _, requests):
            restored = fresh.async_subagents()
            restored.slots = asyncio.Semaphore(0)
            new_host = host_for(fresh, kr)
            await restored.restore("engineering_head", new_host, kr)
            waiting = await projection(storage, run["run_id"], task["task_id"])
            assert waiting["activity"] == "waiting"
            assert waiting["data"]["task_status"] == "queued"
            assert waiting["data"]["task_id"] == task["task_id"]
            assert waiting["data"]["parent_task_id"] == task["parent_task_id"]
            await restored.cancel("engineering_head", new_host, kr, task["task_id"])
            cancelled = await projection(storage, run["run_id"], task["task_id"])
            assert cancelled["activity"] == "idle" and cancelled["seq"] > waiting["seq"]
            assert not requests


async def test_superseded_scope_projects_idle_with_explicit_public_reason(tmp_path, monkeypatch):
    async def provider(body):
        pytest.fail("Superseded queued child must never run")

    async with real_services(tmp_path, monkeypatch, provider) as (services, storage, run, _):
        kr, _ = assignment()
        manager = services.async_subagents()
        manager.slots = asyncio.Semaphore(0)
        old = host_for(services, kr, scope="old")
        task = await manager.start(
            "engineering_head", old, "task", "Old capability", Constitution(), kr
        )
        await manager.restore("engineering_head", host_for(services, kr, scope="replacement"), kr)
        event = await projection(storage, run["run_id"], task["task_id"])
        assert event["activity"] == "idle"
        assert event["data"]["task_status"] == "cancelled"
        assert event["summary"] == "Background R&D stopped: superseded by replacement planning"


@pytest.mark.parametrize(
    ("state", "status", "activity"),
    [
        ("succeeded", "done", "completed"),
        ("cancelled", "cancelled", "idle"),
        ("failed", "error", "error"),
    ],
)
async def test_fresh_owner_reprojects_terminal_receipt_after_event_publication_failed(
    tmp_path, monkeypatch, state, status, activity
):
    async def provider(body):
        pytest.fail("Replaying a terminal receipt must never execute the child")

    async with real_services(tmp_path, monkeypatch, provider) as (services, storage, run, _):
        kr, _ = assignment()
        host = host_for(services, kr)
        manager = services.async_subagents()
        manager.slots = asyncio.Semaphore(0)
        task = await manager.start(
            "engineering_head", host, "committed", "Saved capability", Constitution(), kr
        )
        original = await projection(storage, run["run_id"], task["task_id"])

        async def unavailable_events(*args, **kwargs):
            raise OperationalError("Fixture event connection lost")

        monkeypatch.setattr(services, "emit", unavailable_events)
        with pytest.raises(OperationalError):
            await manager._complete(
                task["task_id"], {"state": state, "reason": "PRIVATE_FAILURE_DETAILS"}, status
            )
        saved = await storage.get_operation(task["task_id"])
        assert saved["status"] == status and saved["result"]["state"] == state
        assert (await projection(storage, run["run_id"], task["task_id"])) == original
        await manager.close()

        async with real_services(
            tmp_path,
            monkeypatch,
            provider,
            storage=storage,
            run=await storage.get_run(run["run_id"]),
            saver=services.agent_checkpointer,
        ) as (fresh, _, _, requests):
            restored = fresh.async_subagents()
            await restored.restore("engineering_head", host_for(fresh, kr), kr)
            event = await projection(storage, run["run_id"], task["task_id"])
            assert event["activity"] == activity
            assert event["data"]["task_status"] == state
            assert event["data"]["task_id"] == task["task_id"]
            assert event["data"]["parent_task_id"] == task["parent_task_id"]
            assert event["seq"] > original["seq"]
            assert "PRIVATE_" not in str(event)
            assert await storage.get_operation(task["task_id"]) == saved
            assert not restored.tasks and not requests


@pytest.mark.parametrize(
    ("state", "status", "activity"),
    [
        ("queued", "pending", "waiting"),
        ("running", "pending", "planning"),
        ("cancelled", "cancelled", "idle"),
        ("failed", "error", "error"),
        ("succeeded", "done", "completed"),
    ],
)
async def test_persisted_task_transition_projects_facts_without_private_payload(
    tmp_path, monkeypatch, state, status, activity
):
    async def provider(body):
        pytest.fail("This fixture tests lifecycle publication without executing child work")

    async with real_services(tmp_path, monkeypatch, provider) as (services, storage, run, _):
        kr, _ = assignment()
        host = host_for(services, kr)
        manager = services.async_subagents()
        manager.slots = asyncio.Semaphore(0)
        task = await manager.start(
            "engineering_head", host, "task", "Public capability", Constitution(), kr
        )
        await manager._complete(
            task["task_id"],
            {
                "state": state,
                "reason": "PRIVATE_PROVIDER_BODY",
                "result": {"report": "PRIVATE_TRANSCRIPT"},
            },
            status,
        )
        saved = await storage.get_operation(task["task_id"])
        assert saved["status"] == status and saved["result"]["state"] == state
        event = await projection(storage, run["run_id"], task["task_id"])
        assert event["activity"] == activity and event["data"]["task_status"] == state
        assert "PRIVATE_" not in str(event)
        assert event["data"]["agent_type"] == "tools_rd_task"
        assert event["data"]["task_id"] == task["task_id"]
