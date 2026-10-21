"""Budget edits retain an established private checkpoint and completed effects."""

import json

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from test_agent_services import assignment, services_with_provider, tool_call
from test_dynamic_services import extracted_deliverable
from typing_extensions import TypedDict

from org_harness.agent_services import AgentServices
from org_harness.api import create_app
from org_harness.models import Constitution
from org_harness.worker import Worker

UNLIMITED = {"max_model_calls": None, "worker_model_calls": None, "max_tool_calls": None}


@pytest.mark.parametrize("legacy_marker", [False, True])
async def test_private_worker_survives_both_budget_directions_and_enforces_finite_turn_cap(
    tmp_path,
    legacy_marker,
):
    kr, work = assignment()
    phase = "unlimited"
    phase_turns = {"unlimited": 0, "finite": 0, "restored": 0}
    prepared = []

    def script(body, requests):
        if body.get("response_format"):
            if "private_progress" in json.loads(body["messages"][-1]["content"]):
                return {
                    "content": json.dumps(
                        {
                            "report": "The append to effect.txt completed exactly once; output.txt exists. Continue verification reads without repeating completed commands."
                        }
                    )
                }
            return extracted_deliverable(body)
        phase_turns[phase] += 1
        results = [item for item in body["messages"] if item["role"] == "tool"]
        if not results:
            # A lost private checkpoint would create new call IDs and repeat
            # this observable side effect; checking only the journal IDs is insufficient.
            return {
                "tool_calls": [
                    tool_call(
                        "run_command", {"command": "echo once >> effect.txt"}, f"append-{phase}"
                    ),
                    tool_call(
                        "write_file",
                        {"path": "output.txt", "content": "Verified task output.\n"},
                        f"write-{phase}",
                    ),
                ]
            }
        if phase == "restored":
            assert any("finite-read-" in str(item) for item in body["messages"])
            return {
                "content": "Completed the original output using preserved verification history."
            }
        return {
            "tool_calls": [
                tool_call("read_file", {"path": "output.txt"}, f"{phase}-read-{phase_turns[phase]}")
            ]
        }

    class State(TypedDict, total=False):
        run_id: str
        status: str
        report: str

    def graph_factory(services, *, checkpointer=None, store=None):
        async def prepare(state):
            prepared.append(state["run_id"])
            return {"status": "running"}

        async def execute(state):
            result = await services.execute(work, kr, Constitution(), [], "", 0)
            return {"status": "completed", "report": result.summary}

        return (
            StateGraph(State)
            .add_node("prepare", prepare)
            .add_node("execute", execute)
            .add_edge(START, "prepare")
            .add_edge("prepare", "execute")
            .add_edge("execute", END)
            .compile(checkpointer=checkpointer)
        )

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        provider,
        storage,
        run,
        requests,
        workspace,
    ):
        saver = InMemorySaver()
        await storage.update_run(run["run_id"], constitution=Constitution().model_dump(mode="json"))

        def factory(settings, storage, current):
            service = AgentServices(settings, storage, current)
            service.model_for = lambda actor=None: provider.model
            return service

        def worker():
            return Worker(
                provider.settings,
                storage,
                checkpointer=saver,
                services_factory=factory,
                graph_factory=graph_factory,
            )

        assert await worker().run_once()
        current = await storage.get_run(run["run_id"])
        assert current["status"] == "queued" and current["review"] is None
        assert current["private_agent_sessions"] is True
        if legacy_marker:
            # Previous releases persisted private threads before recording their
            # origin marker. API budget history must recover that migration.
            await storage.update_run(run["run_id"], private_agent_sessions=False)
        assert phase_turns["unlimited"] == 32
        threads = {
            key
            for key in saver.storage
            if key.startswith(f"{run['run_id']}:private:") and ":summary:" not in key
        }
        assert len(threads) == 1
        app = create_app(provider.settings, storage)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.post(f"/api/runs/{run['run_id']}/pause")).status_code == 200
            paused = (await client.get(f"/api/runs/{run['run_id']}")).json()
            changed = await client.put(
                f"/api/runs/{run['run_id']}/budgets", json={"worker_model_calls": 2}
            )
            assert changed.status_code == 200
            assert changed.json()["limits"]["worker_model_calls"] == 2
            assert (
                await client.post(
                    f"/api/runs/{run['run_id']}/resume",
                    json={"interrupt_id": paused["review"]["interrupt_id"], "action": "continue"},
                )
            ).status_code == 202
            phase = "finite"
            assert await worker().run_once()
            governed = await storage.get_run(run["run_id"])
            # The finite cap remains governed; this deliberately simple outer
            # graph exposes the limit as a failed invocation for explicit retry.
            assert governed["status"] == "failed"
            assert governed["private_agent_sessions"] is True
            assert phase_turns["finite"] == 2
            assert (workspace / "effect.txt").read_text() == "once\n"
            changed = await client.put(
                f"/api/runs/{run['run_id']}/budgets", json={"worker_model_calls": None}
            )
            assert changed.status_code == 200
            assert (await client.post(f"/api/runs/{run['run_id']}/retry")).status_code == 202
            phase = "restored"
            assert await worker().run_once()
        completed = await storage.get_run(run["run_id"])
        assert completed["status"] == "succeeded" and completed["review"] is None
        assert phase_turns["restored"] == 1
        assert (workspace / "effect.txt").read_text() == "once\n"
        assert prepared == [run["run_id"]]
        assert {
            key
            for key in saver.storage
            if key.startswith(f"{run['run_id']}:private:") and ":summary:" not in key
        } == threads
        assert completed["model_calls"] == len(requests)
        commands = [item for item in storage.operations.values() if item["kind"] == "command"]
        assert len(commands) == 1 and commands[0]["status"] == "done"


async def test_fresh_private_session_receives_allowlisted_nested_recovery_evidence(tmp_path):
    kr, work = assignment()
    packet = None

    def script(body, requests):
        nonlocal packet
        if body.get("response_format"):
            return extracted_deliverable(body)
        assert "PRIVATE-STDOUT" not in str(body["messages"])
        assert "PRIVATE-STDERR" not in str(body["messages"])
        if packet is None:
            message = next(
                item["content"]
                for item in body["messages"]
                if "interrupted_command_receipts" in str(item.get("content"))
            )
            packet = json.loads(message[message.index("{") :])
            return {
                "tool_calls": [
                    tool_call(
                        "write_file",
                        {
                            "path": "report.txt",
                            "content": "Inspected existing effects; preserved the original output.",
                        },
                    )
                ]
            }
        return {"content": "Preserved the verified existing effects and saved the report."}

    async with services_with_provider(tmp_path, script, limits=UNLIMITED) as (
        services,
        storage,
        run,
        _,
        _,
    ):
        recovery = {
            "operation_id": "interrupted-command",
            "result": {
                "exit_code": 125,
                "interrupted": True,
                "effects_uncertain": True,
                "execution_stopped": False,
                "process_state": "unverified",
                "artifact_ids": ["receipt-artifact"],
                "recovery_guidance": "Inspect existing processes and output before repair. " * 80,
                "stdout": "PRIVATE-STDOUT",
                "stderr": "PRIVATE-STDERR",
            },
        }
        services.run.update(autonomous_command_recoveries=[recovery])
        await storage.update_run(run["run_id"], autonomous_command_recoveries=[recovery])
        await services.execute(work, kr, Constitution(), [], "", 0)
        receipt = packet["interrupted_command_receipts"][0]
        assert receipt["operation_id"] == recovery["operation_id"]
        assert receipt["result"] == {
            key: recovery["result"][key]
            for key in (
                "exit_code",
                "interrupted",
                "effects_uncertain",
                "execution_stopped",
                "process_state",
                "artifact_ids",
            )
        } | {"recovery_guidance": recovery["result"]["recovery_guidance"][:2000]}
