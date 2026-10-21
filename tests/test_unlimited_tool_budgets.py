"""Tool budgets remain durable across real agents, nested tools, and checkpoint recovery."""

import asyncio
import json

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from test_agent_services import assignment, services_with_provider, tool_call
from test_dynamic_services import extracted_deliverable
from test_mission_tools import environment, register
from typing_extensions import TypedDict

from org_harness.agent_services import AgentServices, WorkerHostTools
from org_harness.api import create_app
from org_harness.models import (
    Constitution,
    EngineeringSpecialistSpec,
    EscalationSignal,
    TacticalPlan,
)
from org_harness.runtime import runtime_config
from org_harness.worker import Worker

UNLIMITED = {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}


async def test_dynamic_worker_exceeds_two_hundred_tool_operations_and_replays_without_recharging(
    tmp_path,
):
    kr, work = assignment()
    work = work.model_copy(
        update={
            "specialist": EngineeringSpecialistSpec(
                name="Durable output verifier",
                instructions="Save the output and verify its contents using recorded file reads.",
                tools=("write_file", "read_file"),
            )
        }
    )

    written, reads_issued = False, 0

    def script(body, requests):
        nonlocal written, reads_issued
        if body.get("response_format"):
            if "private_progress" in json.loads(body["messages"][-1]["content"]):
                return {
                    "content": json.dumps(
                        {
                            "report": "Output.txt is saved. Continue verifying the existing output; completed reads need no replay."
                        }
                    )
                }
            return extracted_deliverable(body)
        if not written:
            written = True
            return {
                "tool_calls": [
                    tool_call(
                        "write_file", {"path": "output.txt", "content": "Verified output"}, "write"
                    )
                ]
            }
        if reads_issued < 201:
            reads = reads_issued
            reads_issued = min(reads + 30, 201)
            return {
                "tool_calls": [
                    tool_call("read_file", {"path": "output.txt"}, f"read-{index}")
                    for index in range(reads, min(reads + 30, 201))
                ]
            }
        return {"content": "Saved output.txt and verified it using the recorded reads."}

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):
        first = await services.execute(work, kr, Constitution(), [], "", 0)
        assert not first.fallback and first.worker_role.startswith("specialist:")
        assert (workspace / "output.txt").read_text() == "Verified output"
        saved = await storage.get_run(run["run_id"])
        assert saved["model_calls"] == len(requests) and saved["tool_calls"] == 202
        first_calls = saved["model_calls"]
        assert len(storage.operations) == 202
        assert all(item["status"] == "done" for item in storage.operations.values())
        artifacts = await storage.list_artifacts(run["run_id"])
        assert len([event for event in storage.events if event["activity"] == "reading"]) == 201

        repeated = await services.execute(work, kr, Constitution(), [], "", 0)
        assert repeated.artifact_ids == first.artifact_ids
        saved = await storage.get_run(run["run_id"])
        assert (saved["model_calls"], saved["tool_calls"]) == (first_calls + 1, 202)
        assert len(requests) == first_calls + 1 and len(storage.operations) == 202
        assert len(await storage.list_artifacts(run["run_id"])) == len(artifacts)
        assert len([event for event in storage.events if event["activity"] == "reading"]) == 201


async def test_finite_tool_cap_still_stops_a_parallel_agent_batch_at_the_exact_limit(tmp_path):
    kr, work = assignment()

    def script(body, requests):
        return {
            "tool_calls": [
                tool_call("read_file", {"path": "input.txt"}, f"read-{index}") for index in range(3)
            ]
        }

    async with services_with_provider(
        tmp_path, script, limits={**UNLIMITED, "max_tool_calls": 2}
    ) as (services, storage, run, requests, workspace):
        (workspace / "input.txt").write_text("Existing input")
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert error.value.kind == "limit_exceeded"
        assert len(requests) == 1
        saved = await storage.get_run(run["run_id"])
        assert (saved["model_calls"], saved["tool_calls"]) == (1, 2)
        assert len(storage.operations) == 2
        assert not await storage.list_artifacts(run["run_id"])


@pytest.mark.parametrize("tool_cap", [None, 3])
async def test_rd_dispatch_and_nested_work_share_the_tool_budget_and_replay_once(
    tmp_path, tool_cap
):
    kr, work = assignment()

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        results = [message for message in body["messages"] if message["role"] == "tool"]
        if body["messages"][0]["content"].startswith("You are tools_rd_lead"):
            if not results:
                return {
                    "tool_calls": [
                        tool_call(
                            "write_file",
                            {"path": "findings.md", "content": "Verified delegated findings"},
                            "rd-write",
                        )
                    ]
                }
            if len(results) == 1:
                return {"tool_calls": [tool_call("read_file", {"path": "findings.md"}, "rd-read")]}
            return {"content": "Verified the delegated findings in the recorded report."}
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "consult_tools_rd",
                        {"requirement": "Research the saved findings", "mode": "research"},
                        "consult",
                    )
                ]
            }
        assert json.loads(results[0]["content"])["result"]["report_artifact_id"]
        return {"content": TacticalPlan(work_packages=(work,)).model_dump_json()}

    async with services_with_provider(
        tmp_path, script, limits={**UNLIMITED, "max_tool_calls": tool_cap}
    ) as (services, storage, run, requests, _):
        if tool_cap is None:
            assert await services.plan_work(kr, Constitution(), [], "")
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (6, 4)
            assert sum(item["kind"] == "tool" for item in storage.operations.values()) == 4
            assert sum(item["kind"] == "rd_delegation" for item in storage.operations.values()) == 1
            artifacts = await storage.list_artifacts(run["run_id"])
            operation_ids = set(storage.operations)
            assert await services.plan_work(kr, Constitution(), [], "")
            saved = await storage.get_run(run["run_id"])
            assert (saved["model_calls"], saved["tool_calls"]) == (6, 4)
            assert set(storage.operations) == operation_ids and len(requests) == 6
            assert len(await storage.list_artifacts(run["run_id"])) == len(artifacts)
        else:
            with pytest.raises(EscalationSignal) as error:
                await services.plan_work(kr, Constitution(), [], "")
            assert error.value.kind == "limit_exceeded"
            saved = await storage.get_run(run["run_id"])
            assert saved["tool_calls"] == 3
            assert not any(
                artifact["name"].startswith("tools_rd_consultation-")
                for artifact in await storage.list_artifacts(run["run_id"])
            )


async def test_registered_tool_crosses_old_limit_with_stale_host_snapshot_and_replays_exactly_once(
    tmp_path,
):
    storage, run, _, catalog, rd, host = await environment(tmp_path)
    assert rd.run["limits"]["max_tool_calls"] == 200
    await storage.update_run(run["run_id"], limits={**run["limits"], **UNLIMITED})
    await storage.reserve_budget(run["run_id"], "tool", amount=200)
    tool = await register(catalog, rd)
    specialist = host(f"specialist:{run['run_id']}:generated-tool-user")
    result = await catalog.invoke(
        specialist, "invoke", tool_id=tool["tool_id"], arguments={"value": 7}
    )
    assert result["output"] == {"doubled": 14}
    saved = await storage.get_run(run["run_id"])
    assert saved["tool_calls"] == 208  # Registration and invocation each journal four operations.
    commands = [item for item in storage.operations.values() if item["kind"] == "command"]
    assert len(commands) == 2 and all(item["status"] == "done" for item in commands)
    assert await register(catalog, rd) == tool
    assert (
        await catalog.invoke(specialist, "invoke", tool_id=tool["tool_id"], arguments={"value": 7})
        == result
    )
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 208
    assert len(storage.operations) == 8


async def test_manual_escalation_tool_honors_unlimited_storage_budget_after_two_hundred_calls(
    tmp_path,
):
    kr, work = assignment()

    def script(body, requests):
        return {
            "tool_calls": [
                tool_call("escalate_blocker", {"reason": "A canonical source is required"})
            ]
        }

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        services,
        storage,
        run,
        requests,
        _,
    ):
        await storage.reserve_budget(run["run_id"], "tool", amount=200)
        with pytest.raises(EscalationSignal) as error:
            await services.execute(work, kr, Constitution(), [], "", 0)
        assert error.value.kind == "blocked" and "canonical source" in error.value.reason
        saved = await storage.get_run(run["run_id"])
        assert (saved["model_calls"], saved["tool_calls"]) == (1, 201)
        assert len(requests) == 1 and not await storage.list_artifacts(run["run_id"])


async def test_unlimited_tool_cap_keeps_real_command_timeout_and_cancellation_controls(tmp_path):
    storage, run, _, _, _, host = await environment(tmp_path)
    await storage.update_run(run["run_id"], limits={**run["limits"], **UNLIMITED})
    worker = host("backend_coder")
    timed_out = await worker.run_command("timeout", "sleep 30", timeout=1)
    assert timed_out["timed_out"] and timed_out["exit_code"] == 124
    command = asyncio.create_task(
        worker.run_command("cancel", "printf begun > started.txt; sleep 30")
    )
    async with asyncio.timeout(5):
        while not (worker.workspace / "started.txt").exists():
            await asyncio.sleep(0.01)
    await storage.command(run["run_id"], "cancel", {})
    with pytest.raises(EscalationSignal) as error:
        await command
    assert error.value.kind == "cancelled"
    assert (await storage.get_run(run["run_id"]))["tool_calls"] == 2


async def test_existing_run_budget_update_and_checkpoint_resume_load_fresh_limits_without_replaying_work(
    tmp_path,
):
    kr, work = assignment()
    work = work.model_copy(
        update={
            "specialist": EngineeringSpecialistSpec(
                name="Resumed verifier", instructions="Save the resumed output."
            )
        }
    )
    preparation_calls = []
    service_limits = []

    def script(body, requests):
        if body.get("response_format"):
            return extracted_deliverable(body)
        results = [message for message in body["messages"] if message["role"] == "tool"]
        if not results:
            return {
                "tool_calls": [
                    tool_call(
                        "write_file",
                        {"path": "resumed.txt", "content": "Completed saved work"},
                        "resume-write",
                    )
                ]
            }
        return {"content": "Saved the completed resumed output."}

    class State(TypedDict, total=False):
        run_id: str
        user_request: str
        constitution: dict
        status: str
        review: dict | None
        report: str

    def graph_factory(services, *, checkpointer=None, store=None):
        graph = StateGraph(State)

        async def prepare(state):
            preparation_calls.append(True)
            host = WorkerHostTools(
                services.storage,
                services.artifacts,
                services.run,
                kr_id=kr.kr_id,
                department="engineering",
                epoch=0,
                role="backend_coder",
                work_package_id="saved-preparation",
                emit=services.emit,
            )
            await host.write_file("prepare-write", "prepared.txt", "Preserved preparation")
            for index in range(199):
                await host.read_file(f"prepare-read-{index}", "prepared.txt")
            return {
                "status": "awaiting_review",
                "review": {
                    "kind": "manual_pause",
                    "reason": "Review saved progress",
                    "allowed_actions": ["continue", "abort"],
                },
            }

        def review(state):
            interrupt(state["review"])
            return {"status": "running", "review": None}

        async def finish(state):
            result = await services.execute(work, kr, Constitution(), [], "", 0)
            return {"status": "completed", "report": result.summary}

        graph.add_node("prepare", prepare)
        graph.add_node("review", review)
        graph.add_node("finish", finish)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "review")
        graph.add_edge("review", "finish")
        graph.add_edge("finish", END)
        return graph.compile(checkpointer=checkpointer)

    async with services_with_provider(
        tmp_path, script, limits={**UNLIMITED, "max_tool_calls": 200}
    ) as (provider, storage, run, requests, workspace):
        await storage.update_run(run["run_id"], constitution=Constitution().model_dump(mode="json"))

        def services_factory(settings, storage, claimed_run):
            services = AgentServices(settings, storage, claimed_run)
            service_limits.append(services.limits.model_dump())
            # Each Worker owns/closes its own configured model; the fixture
            # retains its mocked provider transport across both invocations.
            services.model_for = lambda actor=None: provider.model
            return services

        saver = InMemorySaver()
        first = Worker(
            provider.settings,
            storage,
            services_factory=services_factory,
            graph_factory=graph_factory,
            checkpointer=saver,
        )
        assert await first.run_once()
        paused = await storage.get_run(run["run_id"])
        assert paused["status"] == "paused" and paused["tool_calls"] == 200
        assert paused["model_calls"] == 0 and not requests
        checkpoint = await saver.aget_tuple(runtime_config(run["run_id"]))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(provider.settings, storage)),
            base_url="http://test",
        ) as client:
            response = await client.put(
                f"/api/runs/{run['run_id']}/budgets", json={"max_tool_calls": None}
            )
            assert response.status_code == 200, response.text
            updated = response.json()
            assert updated["status"] == "paused" and updated["tool_calls"] == 200
            assert (
                updated["review"] == paused["review"]
                and updated["limits"]["max_tool_calls"] is None
            )
            assert (await saver.aget_tuple(runtime_config(run["run_id"])))[1]["id"] == checkpoint[
                1
            ]["id"]
            resumed = await client.post(
                f"/api/runs/{run['run_id']}/resume",
                json={"interrupt_id": paused["review"]["interrupt_id"], "action": "continue"},
            )
            assert resumed.status_code == 202, resumed.text
        replacement = Worker(
            provider.settings,
            storage,
            services_factory=services_factory,
            graph_factory=graph_factory,
            checkpointer=saver,
        )
        assert await replacement.run_once()
        result = await storage.get_run(run["run_id"])
        assert result["status"] == "succeeded" and result["review"] is None
        assert (result["model_calls"], result["tool_calls"]) == (3, 201)
        assert preparation_calls == [True] and len(requests) == 3
        assert [limits["max_tool_calls"] for limits in service_limits] == [200, None]
        assert (workspace / "prepared.txt").read_text() == "Preserved preparation"
        assert (workspace / "resumed.txt").read_text() == "Completed saved work"
        assert len(storage.operations) == 201
