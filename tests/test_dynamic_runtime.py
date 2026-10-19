"""Dynamic Engineering assignments retain real identities and deterministic gates."""

from collections import Counter

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from org_harness.models import (
    Constitution,
    Deliverable,
    EngineeringSpecialistSpec,
    Evaluation,
    TriageDecision,
    WorkPackage,
    worker_agent_id,
)
from org_harness.runtime import build_graph, initial_state, runtime_config

RUN_ID = "c4189d48-4720-4d88-9efa-7e59b7fa21e0"


class DynamicServices:
    def __init__(self, *, department="engineering", mode="DEPARTMENTAL", specialist=True):
        self.department = department
        self.mode = mode
        self.specialist = (
            EngineeringSpecialistSpec(
                name="WebGL scene specialist",
                instructions="Build and verify the requested interactive scene.",
                tools=("write_file", "publish_file", "run_command"),
            )
            if specialist
            else None
        )
        self.role = "backend_coder" if department == "engineering" else "market_researcher"
        self.events = []
        self.executions = []
        self.note_calls = []
        self.evaluations = []
        self.planning_calls = 0
        self.tactical_calls = 0
        self.package_count = 1
        self.forged_worker = None
        self.reject_first_gate = False
        self.crash_once = False

    async def triage(self, request, constitution):
        return TriageDecision(
            mode=self.mode,
            departments=(self.department,),
            worker_role=self.role,
            confidence=1,
            source="jev",
            reason="Scripted isolated routing",
            max_revisions=1,
        )

    async def plan(self, *args):
        self.planning_calls += 1
        raise AssertionError("The low-mode graph must not invoke a strategic model")

    async def plan_work(self, kr, constitution, inputs, feedback):
        self.tactical_calls += 1
        return [
            WorkPackage(
                work_package_id=f"scene-{index}",
                kr_id=kr.kr_id,
                role=self.role,
                task="Build and verify the scene",
                acceptance_criteria=("The assigned output works",),
                specialist=self.specialist,
            )
            for index in range(self.package_count)
        ]

    async def execute(self, work, kr, constitution, inputs, feedback, epoch):
        self.executions.append((work, inputs, feedback, epoch))
        if self.crash_once:
            self.crash_once = False
            raise RuntimeError("Simulated worker interruption")
        return Deliverable(
            kr_id=kr.kr_id,
            department=kr.target_department,
            worker_role=self.forged_worker or worker_agent_id(RUN_ID, work),
            summary="Generated and verified the requested scene.",
            artifact_ids=(f"scene-e{epoch}-a{work.execution_attempt}",),
            evidence=("Recorded verification exited successfully",),
            confidence_score=0.9,
        )

    async def evaluate(self, deliverable, criteria, constitution):
        self.evaluations.append((deliverable, criteria))
        passed = not (self.reject_first_gate and len(self.evaluations) == 1)
        return Evaluation(
            passed_constitution=True,
            passed_kr_criteria=passed,
            score=0.9 if passed else 0,
            feedback="Recorded evidence meets the criteria" if passed else "Repair the scene",
            criterion_results=dict.fromkeys(criteria, passed),
            recommended_action="approve" if passed else "retry_worker",
        )

    async def synthesize(self, *args):
        raise AssertionError("The low-mode graph must publish its deterministic report")

    async def publish_report(self, report):
        pass

    async def emit(self, agent_id, activity, summary, **data):
        self.events.append({"agent_id": agent_id, "activity": activity, "data": data})

    async def control(self):
        return None

    async def notes(self, agent_id):
        self.note_calls.append(agent_id)
        return ["Specialist guidance"] if agent_id.startswith("specialist:") else []


async def run(services, *, saver=None):
    graph = build_graph(services, checkpointer=saver or InMemorySaver())
    return graph, await graph.ainvoke(
        initial_state(RUN_ID, "Build the interactive scene", Constitution()), runtime_config(RUN_ID)
    )


async def test_dynamic_engineer_uses_actual_identity_for_notes_events_attempts_and_gates():
    services = DynamicServices()
    _, result = await run(services)
    work = services.executions[0][0]
    agent_id = worker_agent_id(RUN_ID, work)
    assert work.role == "backend_coder"
    assert agent_id != work.role and agent_id.startswith(f"specialist:{RUN_ID}:")
    assert result["status"] == "completed"
    assert result["progress"] == {"direct-1": "passed"}
    assert services.tactical_calls == len(services.executions) == len(services.evaluations) == 1
    assert agent_id in services.note_calls
    assert "Specialist guidance" in services.executions[0][2]
    worker_events = [event for event in services.events if event["agent_id"] == agent_id]
    assert [event["activity"] for event in worker_events] == ["executing", "completed"]
    assert all(
        event["data"]["display_name"] == "WebGL scene specialist"
        and event["data"]["model_parent"] == "backend_coder"
        and event["data"]["parent_agent_id"] == "engineering_head"
        for event in worker_events
    )
    assert any(
        event["agent_id"] == "engineering_head" and event["data"].get("target_agent_id") == agent_id
        for event in services.events
    )
    assert worker_events[-1]["data"]["target_agent_id"] == "engineering_gatekeeper"
    attempts = result["outcomes"]["direct-1"]["attempts"]
    assert next(item for item in attempts if item["stage"] == "worker")["role"] == agent_id
    # The department still owns final acceptance; a specialist cannot self-approve a KR.
    assert services.evaluations[0][0].worker_role == "engineering_head"
    assert len(services.evaluations[0][1]) == 2


async def test_research_cannot_assign_an_engineering_specialist():
    services = DynamicServices(department="research")
    _, result = await run(services)
    assert result["status"] == "awaiting_review"
    assert not services.executions and not services.evaluations
    assert result["outcomes"]["direct-1"]["escalation"]["kind"] == "invalid_plan"
    assert "only to Engineering" in result["review"]["reason"]


async def test_dynamic_specialists_cannot_introduce_unknown_capabilities():
    services = DynamicServices()
    # Model copies can bypass field validation. The deterministic plan boundary
    # must still enforce the capability allowlist before starting a worker.
    services.specialist = services.specialist.model_copy(update={"tools": ("install_anything",)})
    _, result = await run(services)
    assert result["status"] == "awaiting_review"
    assert not services.executions
    assert result["outcomes"]["direct-1"]["escalation"]["kind"] == "invalid_plan"


async def test_dynamic_creation_does_not_expand_the_four_package_limit():
    services = DynamicServices()
    services.package_count = 5
    _, result = await run(services)
    assert result["status"] == "awaiting_review"
    assert not services.executions
    assert "1–4 work packages" in result["review"]["reason"]


@pytest.mark.parametrize("forged", ["backend_coder", "engineering_head", "tools_rd_lead"])
async def test_dynamic_deliverable_cannot_impersonate_a_builtin_agent(forged):
    services = DynamicServices()
    services.forged_worker = forged
    _, result = await run(services)
    agent_id = worker_agent_id(RUN_ID, services.executions[0][0])
    assert result["status"] == "awaiting_review"
    assert result["outcomes"]["direct-1"]["escalation"]["kind"] == "invalid_output"
    assert not services.evaluations
    assert any(
        event["agent_id"] == agent_id and event["activity"] == "error" for event in services.events
    )
    assert not any(
        event["activity"] == "completed"
        for event in services.events
        if event["agent_id"] == agent_id
    )


async def test_dynamic_rework_preserves_identity_and_uses_the_existing_kr_gate_budget():
    services = DynamicServices()
    services.reject_first_gate = True
    _, result = await run(services)
    assert result["status"] == "completed"
    assert len(services.executions) == len(services.evaluations) == 2
    assert [work.execution_attempt for work, *_ in services.executions] == [0, 1]
    assert len({worker_agent_id(RUN_ID, work) for work, *_ in services.executions}) == 1
    assert result["auto_replans"] == 0
    attempts = result["outcomes"]["direct-1"]["attempts"]
    assert [item["approved"] for item in attempts if item["stage"] == "department"] == [False, True]


async def test_rebuilt_graph_retains_checkpointed_specialist_definition_and_actual_identity():
    services = DynamicServices()
    services.crash_once = True
    saver = InMemorySaver()
    with pytest.raises(RuntimeError, match="Simulated worker interruption"):
        await run(services, saver=saver)
    original = services.executions[0][0]
    agent_id = worker_agent_id(RUN_ID, original)
    checkpoints = [checkpoint async for checkpoint in saver.alist(runtime_config(RUN_ID))]
    saved_packages = [
        package
        for checkpoint in checkpoints
        for package in checkpoint.checkpoint["channel_values"].get("work_packages", [])
    ]
    assert any(
        package["specialist"] == original.specialist.model_dump(mode="json")
        for package in saved_packages
    )
    # A fresh planner proposal must not replace an already checkpointed task.
    services.specialist = EngineeringSpecialistSpec(
        name="A different specialist", instructions="Different proposed instructions"
    )
    restored = build_graph(services, checkpointer=saver)
    result = await restored.ainvoke(None, runtime_config(RUN_ID))
    assert result["status"] == "completed"
    assert services.tactical_calls == 1
    assert len(services.executions) == 2
    resumed = services.executions[-1][0]
    assert resumed.specialist == original.specialist
    assert worker_agent_id(RUN_ID, resumed) == agent_id
    assert [work.execution_attempt for work, *_ in services.executions] == [0, 0]
    assert Counter(services.note_calls)[agent_id] == 2
    assert len(services.evaluations) == 1


@pytest.mark.parametrize("mode", ["FAST_TRACK", "DEPARTMENTAL"])
async def test_builtin_assignments_keep_their_existing_identity(mode):
    services = DynamicServices(mode=mode, specialist=False)
    _, result = await run(services)
    assert result["status"] == "completed"
    work = services.executions[0][0]
    assert work.specialist is None and worker_agent_id(RUN_ID, work) == "backend_coder"
    assert not any(event["agent_id"].startswith("specialist:") for event in services.events)
    assert services.tactical_calls == (0 if mode == "FAST_TRACK" else 1)
