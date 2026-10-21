"""Real LangChain background delegations share durable evidence, budgets and ownership."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from openai import AsyncOpenAI
from test_agent_services import assignment, tool_call
from test_dynamic_services import extracted_deliverable

from org_harness import agent_services
from org_harness.agent_services import AgentServices, WorkerHostTools
from org_harness.async_subagents import task_agent_id
from org_harness.autonomy import AutonomousCheckpointYield
from org_harness.config import Settings
from org_harness.models import Constitution, Deliverable, EscalationSignal, TacticalPlan
from org_harness.providers import ZaiChatModel
from org_harness.storage import MemoryStorage
from org_harness.tools import ExpectedToolInputError


@asynccontextmanager
async def real_services(
    tmp_path, monkeypatch, script, *, limits=None, storage=None, run=None, saver=None
):
    storage = storage or MemoryStorage()
    if run is None:
        workspace = tmp_path / "project"
        workspace.mkdir(exist_ok=True)
        run = await storage.create_run(
            {
                "user_request": "Build verified output after investigating the relevant API",
                "workspace_path": str(workspace),
                **({"limits": limits} if limits else {}),
            }
        )
    settings = Settings(_env_file=None, openai_api_key="fixture", data_dir=tmp_path / "data")
    requests = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        message = await script(body)
        return httpx.Response(
            200,
            json={
                "id": f"response-{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "fixture",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "PRIVATE_REASONING",
                            **message,
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def model(settings, selection=None):
        return ZaiChatModel(
            async_client=AsyncOpenAI(
                api_key="fixture",
                base_url="https://provider.invalid/v4",
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )
        )

    monkeypatch.setattr(agent_services, "create_model", model)
    services = AgentServices(settings, storage, run)
    services.agent_checkpointer = saver or InMemorySaver()
    try:
        yield services, storage, run, requests
    finally:
        await services.close()


def host_for(services, kr=None, *, actor="engineering_head", epoch=0, scope="planning"):
    return WorkerHostTools(
        services.storage,
        services.artifacts,
        services.run,
        kr_id=kr.kr_id if kr else "planner",
        version=kr.version if kr else 1,
        department="engineering",
        epoch=epoch,
        role=actor,
        emit=services.emit,
        work_package_id=scope,
    )


@pytest.mark.parametrize("count", [1, 2])
async def test_parent_advances_while_real_rd_agents_overlap_and_final_plan_uses_results(
    tmp_path, monkeypatch, count
):
    kr, work = assignment()
    plan = TacticalPlan(work_packages=(work,))
    started = 0
    all_started = asyncio.Event()
    release = asyncio.Event()
    parent_advanced = asyncio.Event()
    reconciliations = []

    async def script(body):
        payload = (
            json.loads(body["messages"][-1]["content"]) if body.get("response_format") else None
        )
        if payload is not None:
            if "background_results" in payload:
                reconciliations.append(payload)
                assert all(item["status"] == "succeeded" for item in payload["background_results"])
                return {"content": plan.model_dump_json()}
            return extracted_deliverable(body)
        rd = "Original KR (context only)" in body["messages"][0]["content"]
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if rd:
            assert "start_async_task" not in {item["function"]["name"] for item in body["tools"]}
            if not results:
                return {
                    "tool_calls": [
                        tool_call(
                            "write_file",
                            {
                                "path": "finding.md",
                                "content": "The verified API supports the required feature.",
                            },
                            "save",
                        )
                    ]
                }
            nonlocal started
            started += 1
            if started == count:
                all_started.set()
            await release.wait()
            return {"content": "Verified API capability and saved the delegated findings."}
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "start_async_task",
                        {"requirement": f"Investigate API capability {i}", "mode": "research"},
                        f"start-{i}",
                    )
                    for i in range(count)
                ]
            }
        await asyncio.wait_for(all_started.wait(), 5)
        parent_advanced.set()
        assert not release.is_set()
        release.set()
        return {"content": plan.model_dump_json()}

    async with real_services(tmp_path, monkeypatch, script) as (services, storage, run, requests):
        result = await services.plan_work(kr, Constitution(), [], "")
        assert parent_advanced.is_set() and len(result) == 1
        jobs = await storage.list_operations(run["run_id"], kind="async_subagent")
        assert len(jobs) == count and all(item["status"] == "done" for item in jobs)
        assert len(reconciliations) == 1
        assert run.get("private_agent_sessions") is not True
        assert (await storage.get_run(run["run_id"])).get("private_agent_sessions") is not True
        actors = {task_agent_id(run["run_id"], item["operation_id"]) for item in jobs}
        events = [item for item in storage.events if item["agent_id"] in actors]
        assert actors == {item["agent_id"] for item in events}
        assert all(item["data"]["model_parent"] == "tools_rd_lead" for item in events)
        assert all(item["data"]["execution_mode"] == "async" for item in events)
        assert not any("PRIVATE_REASONING" in item["summary"] for item in events)
        provenance = await services._verified_rd_provenance(kr)
        assert len(provenance) == count
        # A replay may re-run the finite lead, but never R&D effects, tool
        # charges or the metered final reconciliation.
        started_before = started
        reconciled_before = len(reconciliations)
        tool_calls = (await storage.get_run(run["run_id"]))["tool_calls"]
        # The second lead response must not repeat the first-run gate assertion.
        release.clear()
        rerun = asyncio.create_task(services.plan_work(kr, Constitution(), [], ""))
        await asyncio.sleep(0)
        release.clear()
        await rerun
        assert started == started_before
        assert len(reconciliations) == reconciled_before
        assert (await storage.get_run(run["run_id"]))["tool_calls"] == tool_calls


async def test_owner_close_then_fresh_service_resumes_private_rd_without_repeating_command(
    tmp_path, monkeypatch
):
    await restart_case(tmp_path, monkeypatch)


async def restart_case(tmp_path, monkeypatch, *, backend=None, saver=None, resume_saver=None):
    kr, _ = assignment()
    blocked = asyncio.Event()
    release = asyncio.Event()
    phase = "first"

    async def script(body):
        if body.get("response_format"):
            return extracted_deliverable(body)
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [
                    tool_call("run_command", {"command": "echo once >> effect.txt"}, "effect"),
                    tool_call(
                        "write_file",
                        {"path": "finding.md", "content": "A verified finding."},
                        "save",
                    ),
                ]
            }
        if phase == "first":
            blocked.set()
            await release.wait()
        return {"content": "The command completed once; the delegated finding is saved."}

    saver = saver or InMemorySaver()
    async with real_services(tmp_path, monkeypatch, script, saver=saver, storage=backend) as (
        services,
        storage,
        run,
        _,
    ):
        host = host_for(services, kr)
        manager = services.async_subagents()
        first = await manager.start(
            "engineering_head", host, "start", "Inspect API", Constitution(), kr, mode="research"
        )
        await asyncio.wait_for(blocked.wait(), 5)
        await storage.update_run(run["run_id"], pause_requested=True)
        await services.close()
        assert all(task.done() for task in manager.tasks.values())
        queued = await storage.get_operation(first["task_id"])
        assert queued["status"] == "pending" and queued["result"]["state"] == "queued"
        command = next(iter(await storage.list_operations(run["run_id"], kind="command")))
        effect = next((tmp_path / "data" / "workspaces").rglob("effect.txt"))
        assert effect.read_text() == "once\n" and command["status"] == "done"
        current = await storage.update_run(run["run_id"], pause_requested=False)
        phase = "resumed"
        async with real_services(
            tmp_path, monkeypatch, script, storage=storage, run=current, saver=resume_saver or saver
        ) as (fresh, _, _, _):
            new_host = host_for(fresh, kr)
            await fresh.async_subagents().restore("engineering_head", new_host, kr)
            replay = await fresh.async_subagents().start(
                "engineering_head",
                new_host,
                "start",
                "Inspect API",
                Constitution(),
                kr,
                mode="research",
            )
            assert replay["task_id"] == first["task_id"]
            await fresh.async_subagents().join("engineering_head", new_host, kr)
            assert effect.read_text() == "once\n"
            assert len(await storage.list_operations(run["run_id"], kind="command")) == 1
            assert (await fresh.async_subagents().list_tasks("engineering_head", new_host, kr))[
                "tasks"
            ][0]["status"] == "succeeded"


async def test_postgres_fresh_service_and_saver_resume_background_command_once(
    tmp_path, monkeypatch, postgres_url
):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from org_harness.storage import PostgresStorage

    storage = PostgresStorage(postgres_url)
    await storage.open()
    try:
        await storage.migrate()
        async with AsyncPostgresSaver.from_conn_string(postgres_url) as first:
            await first.setup()
            async with AsyncPostgresSaver.from_conn_string(postgres_url) as fresh:
                await restart_case(
                    tmp_path, monkeypatch, backend=storage, saver=first, resume_saver=fresh
                )
    finally:
        await storage.close()


async def test_authorization_scope_and_immutable_request_guards_before_execution(
    tmp_path, monkeypatch
):
    async def script(body):
        pytest.fail("Invalid delegation must not call a provider")

    async with real_services(tmp_path, monkeypatch, script) as (services, storage, run, requests):
        kr, _ = assignment()
        manager = services.async_subagents()
        for caller in ("backend_coder", "research_head", "tools_rd_lead", "executive"):
            with pytest.raises(EscalationSignal, match="cannot manage"):
                await manager.start(
                    caller,
                    host_for(services, kr, actor=caller),
                    "start",
                    "Inspect",
                    Constitution(),
                    kr,
                )
        foreign_run = {**run, "run_id": "another-mission"}
        foreign = WorkerHostTools(
            storage,
            services.artifacts,
            foreign_run,
            kr_id=kr.kr_id,
            department="engineering",
            epoch=0,
            role="engineering_head",
            emit=services.emit,
        )
        with pytest.raises(EscalationSignal, match="cannot manage"):
            await manager.start("engineering_head", foreign, "start", "Inspect", Constitution(), kr)
        host = host_for(services, kr)
        # Closed owner persists a queued job, without spawning a process/model.
        await manager.close()
        task = await manager.start("engineering_head", host, "start", "Inspect", Constitution(), kr)
        with pytest.raises(EscalationSignal, match="request changed"):
            await manager.start("engineering_head", host, "start", "Different", Constitution(), kr)
        for stale in (
            host_for(services, kr, epoch=1),
            host_for(services, kr.model_copy(update={"version": 2})),
            host_for(services, kr, scope="another-planning-call"),
        ):
            stale_kr = kr.model_copy(update={"version": stale.version})
            with pytest.raises(ExpectedToolInputError, match="outside"):
                await manager.check("engineering_head", stale, stale_kr, task["task_id"])
        assert not requests and (await storage.get_run(run["run_id"]))["tool_calls"] == 0


async def test_cancel_awaits_child_cleanup_and_does_not_approve_cancelled_work(
    tmp_path, monkeypatch
):
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def script(body):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async with real_services(tmp_path, monkeypatch, script) as (services, storage, run, _):
        kr, _ = assignment()
        host = host_for(services, kr)
        manager = services.async_subagents()
        first = await manager.start(
            "engineering_head", host, "start", "Optional investigation", Constitution(), kr
        )
        await asyncio.wait_for(started.wait(), 5)
        cancelled = await manager.cancel("engineering_head", host, kr, first["task_id"])
        assert cleaned.is_set() and cancelled["status"] == "cancelled" and "result" not in cancelled
        assert all(task.done() for task in manager.tasks.values())
        joined = await manager.join("engineering_head", host, kr)
        assert joined[0]["status"] == "cancelled"
        assert not await storage.list_artifacts(run["run_id"])


async def test_background_yield_preserves_backoff_and_programming_error_stays_fatal(
    tmp_path, monkeypatch
):
    async def script(body):
        pytest.fail("Injected worker failure must precede provider")

    async with real_services(tmp_path, monkeypatch, script) as (services, storage, _, _):
        kr, _ = assignment()
        host = host_for(services, kr)
        phase = "yield"
        original = services._background_service

        def child(current):
            clone = original(current)

            async def fail(*args, **kwargs):
                if phase == "yield":
                    raise AutonomousCheckpointYield(
                        "Provider cooldown", 17, recoverable_failure=True
                    )
                raise ValueError("PRIVATE_INTERNAL_DETAIL")

            clone._execute_worker = fail
            return clone

        services._background_service = child
        manager = services.async_subagents()
        task = await manager.start("engineering_head", host, "start", "Inspect", Constitution(), kr)
        with pytest.raises(AutonomousCheckpointYield) as caught:
            await manager.join("engineering_head", host, kr)
        assert caught.value.delay_seconds == 17 and caught.value.recoverable_failure
        phase = "internal"
        await manager.restore("engineering_head", host, kr)
        with pytest.raises(ValueError, match="PRIVATE_INTERNAL_DETAIL"):
            await manager.join("engineering_head", host, kr)
        stored = await storage.get_operation(task["task_id"])
        assert stored["result"]["kind"] == "internal_error"
        assert "PRIVATE_INTERNAL_DETAIL" not in json.dumps(stored)
        await manager.close()


@pytest.mark.parametrize("limit", ["model", "tool"])
async def test_real_background_agent_obeys_finite_shared_mission_budgets(
    tmp_path, monkeypatch, limit
):
    kr, work = assignment()
    plan = TacticalPlan(work_packages=(work,))

    async def script(body):
        if body.get("response_format"):
            payload = json.loads(body["messages"][-1]["content"])
            return (
                {"content": plan.model_dump_json()}
                if "background_results" in payload
                else extracted_deliverable(body)
            )
        rd = "Original KR (context only)" in body["messages"][0]["content"]
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if rd:
            if not results:
                return {
                    "tool_calls": [
                        tool_call(
                            "write_file",
                            {"path": "finding.md", "content": "Verified capability finding."},
                            "save",
                        )
                    ]
                }
            return {"content": "Saved the delegated findings."}
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "start_async_task",
                        {"requirement": "Inspect API", "mode": "research"},
                        "start",
                    )
                ]
            }
        return {"content": plan.model_dump_json()}

    limits = {
        "max_model_calls": 5 if limit == "model" else 100,
        "max_tool_calls": 2 if limit == "tool" else 200,
    }
    async with real_services(tmp_path, monkeypatch, script, limits=limits) as (
        services,
        storage,
        run,
        requests,
    ):
        with pytest.raises(EscalationSignal) as caught:
            await services.plan_work(kr, Constitution(), [], "")
        assert caught.value.kind == "limit_exceeded"
        saved = await storage.get_run(run["run_id"])
        assert saved[f"{limit}_calls"] == (5 if limit == "model" else 2)
        assert saved["model_calls"] == len(requests)


@pytest.mark.parametrize("unlimited", [False, True])
async def test_mixed_blocking_and_background_delegations_share_durable_scope_allowance(
    tmp_path, monkeypatch, unlimited
):
    async def script(body):
        pytest.fail("Only delegation dispatch/allowance is exercised")

    limits = (
        {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}
        if unlimited
        else None
    )
    async with real_services(tmp_path, monkeypatch, script, limits=limits) as (
        services,
        storage,
        run,
        _,
    ):
        kr, _ = assignment()
        host = host_for(services, kr)
        manager = services.async_subagents()
        await manager.close()  # Leave durable jobs queued without running the provider.
        await manager.reserve_consultation(
            "engineering_head", host, "sync", "First", "research", kr, kind="sync"
        )
        await manager.start(
            "engineering_head", host, "async", "Second", Constitution(), kr, mode="research"
        )
        # A new owner restores the allowance independently of its in-memory counter.
        from org_harness.async_subagents import AsyncSubagentManager

        fresh = AsyncSubagentManager(services)
        await fresh.close()
        if unlimited:
            await fresh.start("engineering_head", host, "third", "Third", Constitution(), kr)
        else:
            with pytest.raises(ExpectedToolInputError, match="consultation limit"):
                await fresh.start("engineering_head", host, "third", "Third", Constitution(), kr)
        assert len(await storage.list_operations(run["run_id"], kind="rd_delegation")) == (
            3 if unlimited else 2
        )


async def test_same_provider_call_id_for_sync_and_async_has_distinct_private_workspace(
    tmp_path, monkeypatch
):
    paths = []

    async def execute(self, work, kr, constitution, inputs, feedback, epoch, host, **kwargs):
        paths.append(host.workspace)
        saved = await host.write_file("write", "tool.py", f"# {work.task}\n")
        return Deliverable(
            kr_id=kr.kr_id,
            department="engineering",
            worker_role=host.actor_id,
            summary="Recorded the delegated capability investigation.",
            artifact_ids=(saved["artifact_id"],),
        )

    monkeypatch.setattr(AgentServices, "_execute_worker", execute)

    async def script(body):
        pytest.fail("Deterministic worker fixture does not use a model")

    async with real_services(tmp_path, monkeypatch, script) as (services, _, _, _):
        kr, _ = assignment()
        host = host_for(services, kr)
        await asyncio.gather(
            services.consult_tools_rd(
                "engineering_head",
                "Blocking investigation",
                Constitution(),
                host,
                "same-id",
                kr,
                mode="research",
            ),
            services.async_subagents().start(
                "engineering_head",
                host,
                "same-id",
                "Background investigation",
                Constitution(),
                kr,
                mode="research",
            ),
        )
        await services.async_subagents().join("engineering_head", host, kr)
        assert len(paths) == 2 and paths[0] != paths[1]
        assert all(path.is_relative_to(tmp_path / "data" / "workspaces") for path in paths)
        assert not (tmp_path / "project" / "tool.py").exists()
        assert (paths[0] / "tool.py").read_text() != (paths[1] / "tool.py").read_text()


@pytest.mark.parametrize("unlimited", [False, True])
@pytest.mark.parametrize("control", ["cancel", "supersede"])
async def test_cancelling_running_rd_command_awaits_process_stop_and_preserves_governed_review(
    tmp_path, monkeypatch, unlimited, control
):
    from org_harness.command_runner import process_identity

    async def script(body):
        return {
            "tool_calls": [
                tool_call("run_command", {"command": "echo $$ > child.pid; sleep 90"}, "sleep")
            ]
        }

    limits = (
        {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}
        if unlimited
        else None
    )
    async with real_services(tmp_path, monkeypatch, script, limits=limits) as (
        services,
        storage,
        run,
        _,
    ):
        kr, _ = assignment()
        host = host_for(services, kr)
        manager = services.async_subagents()
        task = await manager.start(
            "engineering_head", host, "start", "Run capability probe", Constitution(), kr
        )

        async def started():
            while True:
                files = list((tmp_path / "data" / "workspaces").rglob("child.pid"))
                if files:
                    value = files[0].read_text().strip()
                    if value:
                        return int(value)
                await asyncio.sleep(0.01)

        pid = await asyncio.wait_for(started(), 5)
        assert process_identity(pid) is not None
        if control == "cancel":
            await asyncio.wait_for(
                manager.cancel("engineering_head", host, kr, task["task_id"]), 10
            )
        else:
            host = host_for(services, kr, scope="replacement-plan")
            await asyncio.wait_for(manager.restore("engineering_head", host, kr), 10)
            assert (await storage.get_operation(task["task_id"]))["status"] == "cancelled"
        identity = process_identity(pid)
        assert identity is None or identity["state"] == "Z"
        command = (await storage.list_operations(run["run_id"], kind="command"))[0]
        if unlimited:
            assert command["status"] == "done"
            assert command["result"]["effects_uncertain"] and command["result"]["exit_code"] != 0
            joined = await manager.join("engineering_head", host, kr)
            if control == "supersede":
                assert not joined
            else:
                assert joined[0]["status"] == "cancelled"
        else:
            assert command["status"] == "pending"
            with pytest.raises(EscalationSignal) as caught:
                await manager.join("engineering_head", host, kr)
            assert caught.value.kind == "unknown_operation"


async def test_wait_is_bounded_and_closing_retrieves_completed_child_errors(tmp_path, monkeypatch):
    from psycopg import OperationalError

    async def script(body):
        raise OperationalError("fixture database connection lost")

    async with real_services(tmp_path, monkeypatch, script) as (services, storage, run, _):
        kr, _ = assignment()
        host = host_for(services, kr)
        manager = services.async_subagents()
        original = services._background_service

        def child(current):
            clone = original(current)

            async def database_failure(*args, **kwargs):
                raise OperationalError("fixture database connection lost")

            clone._execute_worker = database_failure
            return clone

        services._background_service = child
        task = await manager.start("engineering_head", host, "start", "Inspect", Constitution(), kr)
        with pytest.raises(ExpectedToolInputError, match="30 seconds"):
            await manager.wait("engineering_head", host, kr, task["task_id"], 31)
        with pytest.raises(OperationalError):
            await manager.wait("engineering_head", host, kr, task["task_id"], 1)
        assert (await storage.get_operation(task["task_id"]))["status"] == "pending"
        await manager.close()
        assert all(item.done() for item in manager.tasks.values())


async def test_replacement_scope_stops_only_older_same_caller_kr_jobs(tmp_path, monkeypatch):
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def script(body):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async with real_services(tmp_path, monkeypatch, script) as (services, storage, run, _):
        kr, _ = assignment()
        other_kr = kr.model_copy(update={"kr_id": "another-kr"})
        manager = services.async_subagents()
        old = host_for(services, kr, scope="old-plan")
        same = await manager.start("engineering_head", old, "old", "Old scope", Constitution(), kr)
        other = await manager.start(
            "engineering_head",
            host_for(services, other_kr),
            "other",
            "Other KR",
            Constitution(),
            other_kr,
        )
        planner = await manager.start(
            "planner",
            host_for(services, actor="planner"),
            "planner",
            "Other caller",
            Constitution(),
        )
        await asyncio.wait_for(started.wait(), 5)
        replacement = host_for(services, kr, scope="new-plan")
        await manager.restore("engineering_head", replacement, kr)
        assert cleaned.is_set()
        assert (await storage.get_operation(same["task_id"]))["status"] == "cancelled"
        assert (await storage.get_operation(other["task_id"]))["status"] == "pending"
        assert (await storage.get_operation(planner["task_id"]))["status"] == "pending"
        assert (await manager.list_tasks("engineering_head", replacement, kr))["tasks"] == []
        events = [
            event
            for event in storage.events
            if event["agent_id"] == task_agent_id(run["run_id"], same["task_id"])
        ]
        assert events[-1]["summary"] == "Background R&D stopped: superseded by replacement planning"
        assert events[-1]["data"]["task_id"] == same["task_id"]
