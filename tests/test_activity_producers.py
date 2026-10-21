"""Activity records describe real work and handoffs without exposing private model data."""

import asyncio
import json
from types import SimpleNamespace
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from test_agent_services import approve, assignment, services_with_provider, tool_call
from test_dynamic_services import extracted_deliverable
from test_runtime import Services, invoke, kr

from org_harness.config import Settings
from org_harness.models import (
    Constitution,
    EngineeringSpecialistSpec,
    EscalationSignal,
    TriageDecision,
    worker_agent_id,
)
from org_harness.storage import MemoryStorage
from org_harness.worker import Worker


async def test_long_model_turn_and_read_only_steps_are_visible_without_private_content(
    tmp_path, monkeypatch
):
    _, base_work = assignment()
    model_started = asyncio.Event()
    release_model = asyncio.Event()
    spec = EngineeringSpecialistSpec(
        name="Evidence reader",
        instructions="Read the supplied sources and write the public result.",
    )
    seeded_artifact = None
    assigned = None

    def script(body, requests):
        if body.get("response_format"):
            payload = json.loads(body["messages"][-1]["content"])
            return (
                {"content": json.dumps(approve(payload["acceptance_criteria"]))}
                if "recorded_artifact_evidence" in payload
                else extracted_deliverable(body)
            )
        results = [item for item in body["messages"] if item["role"] == "tool"]
        actions = [
            tool_call("read_file", {"path": "secret.txt"}, "read-secret"),
            tool_call("read_artifact", {"artifact_id": seeded_artifact}, "read-artifact"),
            tool_call("read_file", {"path": "second.txt"}, "read-second"),
            tool_call(
                "write_file", {"path": "result.md", "content": "Verified public result"}, "write"
            ),
        ]
        return (
            {"tool_calls": [actions[len(results)]]}
            if len(results) < len(actions)
            else {"content": "Completed the public result file."}
        )

    async with services_with_provider(tmp_path, script) as (
        services,
        storage,
        run,
        requests,
        workspace,
    ):
        await storage.update_run(run["run_id"], constitution=Constitution().model_dump())
        (workspace / "secret.txt").write_text("PRIVATE_FILE_CREDENTIAL_SENTINEL")
        (workspace / "second.txt").write_text("PRIVATE_SECOND_FILE_SENTINEL")
        artifact = await services.artifacts.save(
            "reference.md", "PRIVATE_ARTIFACT_SENTINEL", kr_id="direct-1", kind="source"
        )
        seeded_artifact = artifact["artifact_id"]

        async def triage(*args):
            return TriageDecision(
                mode="DEPARTMENTAL",
                departments=("engineering",),
                worker_role="backend_coder",
                confidence=1,
                source="jev",
                reason="Scripted route",
                max_revisions=1,
            )

        async def plan_work(key_result, *args):
            nonlocal assigned
            assigned = base_work.model_copy(update={"kr_id": key_result.kr_id, "specialist": spec})
            return [assigned]

        model_request = services.model_request

        async def delayed(request):
            if not model_started.is_set():
                model_started.set()
                await release_model.wait()
            return await model_request(request)

        monkeypatch.setattr(services, "triage", triage)
        monkeypatch.setattr(services, "plan_work", plan_work)
        monkeypatch.setattr(services, "model_request", delayed)
        worker = Worker(
            services.settings,
            storage,
            services_factory=lambda *_: services,
            checkpointer=InMemorySaver(),
        )
        execution = asyncio.create_task(worker.run_once())
        try:
            await asyncio.wait_for(model_started.wait(), 2)
            identity = worker_agent_id(run["run_id"], assigned)
            snapshot = await storage.office_snapshot()
            active = {
                item["agent_id"]
                for item in snapshot["agents"]
                if item["activity"] in {"planning", "executing", "reading", "writing", "reviewing"}
            }
            assert active == {identity}
            latest = next(item for item in snapshot["agents"] if item["agent_id"] == identity)
            assert latest["activity"] == "executing"
            assert latest["kr_id"] == assigned.kr_id == "direct-1"
            assert latest["data"]["phase"] == "model_request"
            assert latest["data"]["display_name"] == spec.name
            release_model.set()
            assert await asyncio.wait_for(execution, 3)
        finally:
            release_model.set()
            if not execution.done():
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
        assert (workspace / "result.md").read_text() == "Verified public result"
        events = await storage.events_after(0, run["run_id"])
        actor_events = [item for item in events if item["agent_id"] == identity]
        reads = [item for item in actor_events if item["activity"] == "reading"]
        assert [item["summary"] for item in reads] == [
            "Read secret.txt",
            "Read artifact reference.md",
            "Read second.txt",
        ]
        assert sum(item["data"].get("phase") == "model_request" for item in actor_events) == 5
        assert all(
            item["kr_id"] == assigned.kr_id
            for item in actor_events
            if item["data"].get("phase") == "model_request"
        )
        public = json.dumps(events)
        assert all(
            marker not in public
            for marker in [
                "PRIVATE_FILE_CREDENTIAL_SENTINEL",
                "PRIVATE_SECOND_FILE_SENTINEL",
                "PRIVATE_ARTIFACT_SENTINEL",
                "private-provider-data",
                "fixture-key",
            ]
        )
        current = await storage.get_run(run["run_id"])
        assert current["status"] == "succeeded"
        assert current["model_calls"] == len(requests) == 7
        assert current["tool_calls"] == 4


@pytest.mark.parametrize("unexpected", [False, True])
@pytest.mark.parametrize("caller", ["engineering_head", "planner"])
async def test_rd_failure_records_its_actor_and_preserves_safe_reason(
    tmp_path, monkeypatch, unexpected, caller
):
    key_result, _ = assignment()
    reason = "The delegated research source is unavailable"
    async with services_with_provider(tmp_path, lambda *_: {}) as (services, storage, run, _, _):

        async def blocked(*args, **kwargs):
            if unexpected:
                raise RuntimeError("PRIVATE_EXCEPTION_CREDENTIAL_SENTINEL")
            raise EscalationSignal("missing_resource", reason)

        monkeypatch.setattr(services, "_execute_worker", blocked)
        delegated_kr = key_result if caller == "engineering_head" else None
        parent = services._planning_host(caller, delegated_kr)
        with pytest.raises(RuntimeError if unexpected else EscalationSignal):
            await services.consult_tools_rd(
                caller,
                "Find a source",
                Constitution(),
                parent,
                "consult",
                delegated_kr,
                mode="research",
            )
        events = await storage.events_after(0, run["run_id"])
        rd_events = [item for item in events if item["agent_id"] == "tools_rd_lead"]
        assert rd_events[-1]["activity"] == "error"
        assert rd_events[-1]["summary"] == (
            "Tools R&D stopped unexpectedly (RuntimeError)" if unexpected else reason
        )
        assert rd_events[-1]["data"]["display_name"] == "Tools R&D Lead"
        assert rd_events[-1]["data"]["parent_agent_id"] == caller
        assert rd_events[-1]["kr_id"] == (key_result.kr_id if delegated_kr else "planner-tools")
        assert any(item["agent_id"] == caller and item["activity"] == "waiting" for item in events)
        assert "PRIVATE_EXCEPTION_CREDENTIAL_SENTINEL" not in json.dumps(events)


async def test_rd_deadline_records_its_own_timeout_activity(tmp_path, monkeypatch):
    key_result, _ = assignment()
    async with services_with_provider(tmp_path, lambda *_: {}, limits={"worker_timeout": 0.02}) as (
        services,
        storage,
        run,
        _,
        _,
    ):

        async def blocked(*args, **kwargs):
            await asyncio.Event().wait()

        monkeypatch.setattr(services, "_execute_worker", blocked)
        parent = services._planning_host("engineering_head", key_result)
        with pytest.raises(EscalationSignal) as error:
            await services.consult_tools_rd(
                "engineering_head",
                "Research a capability",
                Constitution(),
                parent,
                "timeout",
                key_result,
                mode="research",
            )
        assert error.value.kind == "worker_timeout"
        rd = [
            item
            for item in await storage.events_after(0, run["run_id"])
            if item["agent_id"] == "tools_rd_lead"
        ]
        assert rd[-1]["activity"] == "error"
        assert rd[-1]["data"]["kind"] == "worker_timeout"
        assert rd[-1]["summary"] == error.value.reason
        assert not any(item["activity"] == "completed" for item in rd)


@pytest.mark.parametrize("stage", ["head", "worker_gate", "department_gate"])
async def test_head_and_reviewer_failures_record_the_actor_that_failed(stage):
    services = Services(kr("implementation", "engineering"))
    reason = "Validated public provider failure"
    if stage == "head":

        async def planning(*args):
            raise EscalationSignal("provider_error", reason)

        services.plan_work = planning
    else:

        def judge(deliverable, criteria):
            if (stage == "worker_gate") == (deliverable.worker_role == "backend_coder"):
                raise EscalationSignal("provider_error", reason)

        services.judge = judge
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    actor = "engineering_head" if stage == "head" else "engineering_gatekeeper"
    errors = [
        (args, data) for args, data in services.events if args[0] == actor and args[1] == "error"
    ]
    assert errors and errors[-1][0][2] == reason
    assert errors[-1][1]["kind"] == "provider_error"


class LifecycleState(TypedDict, total=False):
    status: str
    report: str


@pytest.mark.parametrize(
    ("status", "activity"), [("completed", "completed"), ("failed", "error"), ("cancelled", "idle")]
)
async def test_worker_final_activity_matches_terminal_result(tmp_path, status, activity):
    storage = MemoryStorage()
    run = await storage.create_run({"user_request": "Check lifecycle", "constitution": {}})

    def graph_factory(services, *, checkpointer=None, store=None):
        graph = StateGraph(LifecycleState)
        graph.add_node("finish", lambda _: {"status": status, "report": "Recorded result"})
        graph.add_edge(START, "finish")
        graph.add_edge("finish", END)
        return graph.compile(checkpointer=checkpointer)

    worker = Worker(
        Settings(_env_file=None, harness_test_mode=True, data_dir=tmp_path),
        storage,
        graph_factory=graph_factory,
        services_factory=lambda *_: SimpleNamespace(),
        checkpointer=InMemorySaver(),
    )
    assert await worker.run_once()
    events = await storage.events_after(0, run["run_id"])
    assert events[0]["activity"] == "waiting"
    assert events[-1]["activity"] == activity
