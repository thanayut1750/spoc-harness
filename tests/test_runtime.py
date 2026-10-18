"""Behavioral graph tests run genuine nested graphs with scripted model services."""

import asyncio
import json
from collections import Counter

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from org_harness.models import (
    AttemptRecord,
    Constitution,
    Deliverable,
    EscalationSignal,
    Evaluation,
    KeyResult,
    StrategicObjective,
    TriageDecision,
    WorkPackage,
)
from org_harness.runtime import (
    build_graph,
    department_context,
    enrich_review_context,
    gate_approved,
    initial_state,
    merge_keyed,
    runtime_config,
    validate_plan,
    validate_review_decision,
)
from org_harness.storage import ArtifactNotFoundError, RunNotFoundError


def kr(identifier="research", department="research", dependencies=()):
    return KeyResult(
        kr_id=identifier,
        description=f"Complete {identifier}",
        acceptance_criteria=(f"{identifier} accepted",),
        target_department=department,
        dependency_kr_ids=dependencies,
    )


def objective(*krs):
    return StrategicObjective(objective_id="objective", title="Mission", key_results=krs)


class Services:
    def __init__(self, *krs):
        self.objectives = [objective(*(krs or (kr(),)))]
        self.planning_calls = 0
        self.tactical_calls = Counter()
        self.executions = []
        self.evaluations = []
        self.events = []
        self.note_calls = []
        self.active = 0
        self.max_active = 0
        self.command = None
        self.block = None
        self.judge = None
        self.packages = None
        self.resolved_operations = 0
        self.governance_halt = None
        self.synthesis_calls = 0
        self.published_reports = []

    async def plan(self, request, constitution):
        self.planning_calls += 1
        return self.objectives

    async def plan_work(self, key_result, constitution, inputs, feedback):
        self.tactical_calls[key_result.kr_id] += 1
        if self.packages:
            return self.packages(key_result)
        role = (
            "market_researcher" if key_result.target_department == "research" else "backend_coder"
        )
        return [
            WorkPackage(
                work_package_id=f"{key_result.kr_id}-work",
                kr_id=key_result.kr_id,
                role=role,
                task=key_result.description,
                acceptance_criteria=("work accepted",),
            )
        ]

    async def execute(self, work, key_result, constitution, inputs, feedback, epoch):
        self.executions.append((work, key_result, inputs, feedback, epoch))
        self.active += 1
        self.max_active = max(self.active, self.max_active)
        try:
            await asyncio.sleep(0.005)
            if self.block:
                self.block(work, key_result, epoch)
            return Deliverable(
                kr_id=key_result.kr_id,
                department=key_result.target_department,
                worker_role=work.role,
                summary=f"Approved output from {work.work_package_id}",
                artifact_ids=(f"artifact-{key_result.kr_id}-v{key_result.version}-e{epoch}",),
                evidence=("The acceptance check returned exit code 0",),
                confidence_score=0.9,
            )
        finally:
            self.active -= 1

    async def evaluate(self, deliverable, criteria, constitution):
        self.evaluations.append((deliverable, criteria))
        if self.judge:
            result = self.judge(deliverable, criteria)
            if result is not None:
                return result
        return evaluation(criteria)

    async def synthesize(self, request, objectives, outcomes):
        self.synthesis_calls += 1
        assert all(o.status == "passed" for o in outcomes)
        return "The mission was completed with approved evidence."

    async def publish_report(self, report):
        self.published_reports.append(report)

    async def emit(self, *args, **kwargs):
        self.events.append((args, kwargs))

    async def control(self):
        if self.command == "cancel":
            return "cancel"
        if self.governance_halt:
            return "suspend"
        return self.command

    async def notes(self, agent_id):
        self.note_calls.append(agent_id)
        return []

    async def resolve_operation(self, decision):
        self.resolved_operations += 1

    async def halt_for_review(self, kind, reason):
        self.governance_halt = {"kind": kind, "reason": reason}

    async def resolve_review(self, decision):
        self.governance_halt = None


class TriagedServices(Services):
    def __init__(self, mode="FAST_TRACK", department="engineering", *key_results):
        super().__init__(*key_results)
        self.triage_calls = 0
        self.decision = TriageDecision(
            mode=mode,
            departments=(department,) if mode != "FULL_PYRAMID" else ("research", "engineering"),
            worker_role="market_researcher" if department == "research" else "backend_coder",
            confidence=0.95,
            source="jev",
            reason="Scripted typed triage",
            max_revisions=1 if mode != "FULL_PYRAMID" else 2,
        )

    async def triage(self, request, constitution):
        self.triage_calls += 1
        return self.decision


def evaluation(criteria, **updates):
    return Evaluation(
        **{
            "passed_constitution": True,
            "passed_kr_criteria": True,
            "score": 0.9,
            "feedback": "The criteria were checked",
            "recommended_action": "approve",
            "criterion_results": dict.fromkeys(criteria, True),
            **updates,
        }
    )


async def invoke(services, constitution=None, checkpointer=None, run_id="test"):
    graph = build_graph(services, checkpointer=checkpointer or InMemorySaver())
    state = initial_state(run_id, "Complete the mission", constitution or Constitution())
    result = await graph.ainvoke(state, runtime_config(run_id))
    return graph, result


async def test_parallel_departments_wait_for_approved_dependencies_and_isolate_context():
    research = kr("market")
    independent = kr("architecture", "engineering")
    dependent = kr("implementation", "engineering", ("market", "architecture"))
    services = Services(research, independent, dependent)
    graph, result = await invoke(services)
    assert result["status"] == "completed"
    assert services.max_active == 2
    assert len(services.executions) == 3
    assert all(state == "passed" for state in result["progress"].values())
    assert len(result["outcomes"]) == 3
    inputs = next(call[2] for call in services.executions if call[1].kr_id == "implementation")
    assert {item.kr_id for item in inputs} == {"market", "architecture"}
    assert all(item.worker_role.endswith("_head") for item in inputs)
    assert "v1, epoch 0: passed" in result["report"]
    assert "artifact-market-v1-e0" in result["report"]
    planner_events = [event for event in services.events if event[0][0] == "planner"]
    assert planner_events[-1][0][1] == "completed"
    transfers = [
        (args[0], data["target_agent_id"], data["kr_id"])
        for args, data in services.events
        if "target_agent_id" in data
    ]
    expected_transfers = []
    for key_result in (research, independent, dependent):
        department = key_result.target_department
        role = "market_researcher" if department == "research" else "backend_coder"
        expected_transfers.extend(
            [
                ("executive", f"{department}_head", key_result.kr_id),
                (f"{department}_head", role, key_result.kr_id),
                (role, f"{department}_gatekeeper", key_result.kr_id),
                (f"{department}_head", "executive", key_result.kr_id),
            ]
        )
    assert Counter(transfers) == Counter(expected_transfers)
    assert (await graph.aget_state(runtime_config("test"))).next == ()
    context = department_context(result, dependent)
    assert "messages" not in context
    assert set(context) == {
        "run_id",
        "constitution",
        "kr",
        "epoch",
        "inputs",
        "feedback",
        "revisions",
        "accepted",
        "attempts",
        "work_index",
        "execution_mode",
        "revision_limit",
        "direct_worker_role",
    }


async def test_one_active_kr_per_department_and_fresh_worker_invocations():
    services = Services(kr("first"), kr("second"), kr("third"))
    _, result = await invoke(services)
    assert result["status"] == "completed"
    assert services.max_active == 1
    assert [call[1].kr_id for call in services.executions] == ["first", "second", "third"]
    assert all(call[2] == [] for call in services.executions)
    assert set(result["outcomes"]) == {"first", "second", "third"}


async def test_worker_and_department_share_revision_budget_then_only_one_run_replan():
    services = Services()

    def reject(deliverable, criteria):
        # Initial worker fails once; the complete KR then fails. Both failures
        # consume one shared epoch budget before the next worker failure.
        return evaluation(criteria, score=0.2, feedback="Repair failing evidence")

    services.judge = reject
    graph, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert result["auto_replans"] == 1
    assert len(services.executions) == 6  # initial + two reworks, twice
    assert [call[0].execution_attempt for call in services.executions] == [0, 1, 2, 0, 1, 2]
    assert result["epochs"] == {"research": 1}
    assert result["review"]["kind"] == "blocked"
    packet = result["review"]["context"]
    assert packet["mission"] == "Complete the mission"
    assert packet["retry_summary"] == {
        "automatic_replans_used": 1,
        "automatic_replans_limit": 1,
        "revision_limit": 2,
        "attempts_recorded": 6,
    }
    reviewed = packet["key_results"][0]
    assert reviewed["kr_id"] == "research"
    assert reviewed["acceptance_criteria"] == ["research accepted"]
    assert len(reviewed["attempts"]) == 6
    assert {attempt["epoch"] for attempt in reviewed["attempts"]} == {0, 1}
    assert reviewed["evaluation"]["score"] == 0.2
    assert reviewed["artifact_ids"]
    assert "new execution epoch" in packet["action_implications"]["provide_context"]
    assert result["outcomes"]["research"]["deliverable"] is not None
    assert result["outcomes"]["research"]["evaluation"] is not None
    assert services.planning_calls == 1
    assert all(call[3] for call in services.executions[1:])
    before = len(services.executions)
    services.judge = None
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "provide_context",
                "context": "Use corrected evidence",
            }
        ),
        runtime_config("test"),
    )
    assert result["status"] == "completed"
    assert result["auto_replans"] == 1
    assert len(services.executions) == before + 1
    assert services.executions[-1][0].execution_attempt == 0
    assert services.planning_calls == 1
    assert all(escalation["resolved"] for escalation in result["escalations"].values())


async def test_provider_cannot_select_worker_execution_attempt():
    services = Services()
    services.packages = lambda key_result: [
        WorkPackage(
            work_package_id="model-proposed-work",
            kr_id=key_result.kr_id,
            role="market_researcher",
            task=key_result.description,
            acceptance_criteria=("work accepted",),
            execution_attempt=5,
        )
    ]

    def reject_first_attempt(deliverable, criteria):
        if len(services.executions) == 1:
            return evaluation(criteria, score=0.2, feedback="Correct the first attempt")
        return None

    services.judge = reject_first_attempt
    _, result = await invoke(services)
    assert result["status"] == "completed"
    assert [call[0].execution_attempt for call in services.executions] == [0, 1]
    assert services.tactical_calls["research"] == 1


async def test_department_gate_cannot_bypass_shared_worker_revision_budget():
    services = Services()
    worker_reviews = 0

    def reject(deliverable, criteria):
        nonlocal worker_reviews
        if not deliverable.worker_role.endswith("_head"):
            worker_reviews += 1
            if worker_reviews % 2:
                return evaluation(criteria, score=0.1, feedback="Worker correction required")
            return None
        return evaluation(criteria, score=0.1, feedback="Whole KR still fails")

    services.judge = reject
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    # Each epoch: reject worker, pass worker, reject department, reject worker.
    assert len(services.executions) == 6
    assert services.tactical_calls["research"] == 4
    assert all(o["status"] != "passed" for o in result["outcomes"].values())


async def test_constitution_failure_skips_retries_and_auto_replan():
    services = Services(kr("research"), kr("engineering", "engineering"))
    services.judge = lambda deliverable, criteria: evaluation(
        criteria,
        passed_constitution=False,
        constitution_violations=("Observed prohibited action",),
        feedback="Prohibited action detected",
    )
    graph, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert result["auto_replans"] == 0
    assert result["review"]["kind"] == "constitution_violation"
    outcome = result["outcomes"]["research"]
    assert outcome["evaluation"]["passed_constitution"] is False
    assert outcome["deliverable"]["summary"]
    assert outcome["attempts"][0]["stage"] == "worker"
    assert len(services.executions) == 2
    assert not any(status == "passed" for status in result["progress"].values())
    result = await graph.ainvoke(Command(resume={"action": "abort"}), runtime_config("test"))
    assert result["status"] == "cancelled"
    assert services.planning_calls == 1
    assert len(services.executions) == 2


async def test_missing_evidence_under_default_mission_is_quality_failure_not_policy_violation():
    services = Services()
    services.judge = lambda deliverable, criteria: evaluation(
        criteria,
        passed_constitution=False,
        passed_kr_criteria=False,
        score=0,
        feedback="Traceable evidence is missing; complete the work.",
        criterion_results=dict.fromkeys(criteria, False),
    )
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert result["review"]["kind"] == "blocked"
    assert result["auto_replans"] == 1
    assert not services.governance_halt
    assert len(services.executions) == 6
    assert (
        result["review"]["context"]["blockers"][0]["classification"]
        == "quality_or_execution_failure"
    )


async def test_explicit_constitution_policies_remain_enforced_for_legacy_judges():
    services = Services()
    services.judge = lambda deliverable, criteria: evaluation(
        criteria,
        passed_constitution=False,
        feedback="Observed prohibited network access",
    )
    _, result = await invoke(
        services, Constitution(prohibited_actions=("Do not access the network",))
    )
    assert result["review"]["kind"] == "constitution_violation"
    assert result["auto_replans"] == 0
    assert len(services.executions) == 1


async def test_structured_policy_violation_overrides_contradictory_approval():
    services = Services()
    services.judge = lambda deliverable, criteria: evaluation(
        criteria,
        passed_constitution=True,
        passed_kr_criteria=True,
        score=1,
        constitution_violations=("Observed prohibited action despite the approval flag",),
    )
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert result["review"]["kind"] == "constitution_violation"
    assert result["auto_replans"] == 0
    assert len(services.executions) == 1
    assert services.governance_halt
    outcome = result["outcomes"]["research"]
    assert outcome["status"] == "escalated"
    assert not gate_approved(
        Deliverable.model_validate(outcome["deliverable"]),
        Evaluation.model_validate(outcome["evaluation"]),
        ("work accepted",),
    )


async def test_one_blocker_in_each_parallel_department_uses_one_global_replan():
    services = Services(kr("research"), kr("engineering", "engineering"))

    def blocked(*args):
        raise EscalationSignal("blocked", "Missing required context")

    services.block = blocked
    _, result = await invoke(services)
    assert result["auto_replans"] == 1
    assert result["status"] == "awaiting_review"
    assert len(services.executions) == 4
    assert len(result["escalations"]) == 4
    assert set(result["review"]["kr_ids"]) == {"research", "engineering"}


async def test_unknown_host_command_requires_explicit_human_retry():
    services = Services()

    def unknown(*args):
        raise EscalationSignal("unknown_operation", "Command outcome is unknown after crash")

    services.block = unknown
    graph, result = await invoke(services)
    assert result["auto_replans"] == 0
    assert result["review"]["allowed_actions"] == ["retry_operation", "abort"]
    services.block = None
    result = await graph.ainvoke(
        Command(resume={"action": "retry_operation"}), runtime_config("test")
    )
    assert result["status"] == "completed"
    assert services.resolved_operations == 1


async def test_human_kr_revision_invalidates_transitive_approved_dependencies():
    services = Services(
        kr("first"), kr("second", "engineering", ("first",)), kr("third", "research", ("second",))
    )

    def blocked(work, key_result, epoch):
        if key_result.kr_id == "third":
            raise EscalationSignal("blocked", "Requirements changed")

    services.block = blocked
    graph, result = await invoke(services)
    assert result["progress"]["first"] == "passed"
    assert result["progress"]["second"] == "passed"
    assert result["status"] == "awaiting_review"
    services.block = None
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "revise_kr",
                "kr_id": "first",
                "acceptance_criteria": ["Revised criterion"],
            }
        ),
        runtime_config("test"),
    )
    assert result["status"] == "completed"
    assert result["outcomes"]["first"]["version"] == 2
    assert result["epochs"] == {"first": 1, "second": 1, "third": 2}
    assert Counter(call[1].kr_id for call in services.executions) == {
        "first": 2,
        "second": 2,
        "third": 3,
    }
    current_second = [call for call in services.executions if call[1].kr_id == "second"][-1]
    assert current_second[2][0].artifact_ids == ("artifact-first-v2-e1",)


async def test_review_checkpoint_survives_graph_reconstruction_without_reexecuting_work():
    services = Services()
    services.command = "pause"
    saver = InMemorySaver()
    _, result = await invoke(services, checkpointer=saver)
    assert result["review"]["kind"] == "manual_pause"
    assert not services.executions
    graph = build_graph(services, checkpointer=saver)
    services.command = None
    result = await graph.ainvoke(Command(resume={"action": "continue"}), runtime_config("test"))
    assert result["status"] == "completed"
    assert services.planning_calls == 1
    assert len(services.executions) == 1


async def test_mid_worker_recovery_restores_nested_checkpoint_without_replanning():
    services = Services()
    failed = False

    def crash_once(*args):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("Simulated process crash")

    services.block = crash_once
    saver = InMemorySaver()
    graph = build_graph(services, checkpointer=saver)
    with pytest.raises(RuntimeError, match="Simulated process crash"):
        await graph.ainvoke(
            initial_state("crash", "Complete mission", Constitution()), runtime_config("crash")
        )
    restored = build_graph(services, checkpointer=saver)
    result = await restored.ainvoke(None, runtime_config("crash"))
    assert result["status"] == "completed"
    assert services.planning_calls == 1
    assert services.tactical_calls == {"research": 1}
    # A real AgentServices execution reuses the tool journal when the worker node
    # is retried; this graph-level test checks that completed planning is durable.
    assert len(services.executions) == 2
    assert [call[0].execution_attempt for call in services.executions] == [0, 0]
    assert len(services.evaluations) == 2


async def test_durable_constitution_halt_survives_crash_before_outcome_checkpoint():
    services = Services()
    services.judge = lambda deliverable, criteria: evaluation(
        criteria,
        passed_constitution=False,
        constitution_violations=("Observed constitution violation",),
        feedback="Constitution violation evidence",
    )

    async def halt_then_crash(kind, reason):
        services.governance_halt = {"kind": kind, "reason": reason}
        raise RuntimeError("Crash after persisting governance halt")

    services.halt_for_review = halt_then_crash
    saver = InMemorySaver()
    graph = build_graph(services, checkpointer=saver)
    with pytest.raises(RuntimeError, match="Crash after persisting"):
        await graph.ainvoke(
            initial_state("halt", "Complete mission", Constitution()), runtime_config("halt")
        )
    restored = build_graph(services, checkpointer=saver)
    result = await restored.ainvoke(None, runtime_config("halt"))
    assert result["status"] == "awaiting_review"
    assert result["review"]["kind"] == "constitution_violation"
    assert result["auto_replans"] == 0
    assert len(services.executions) == 1
    assert len(services.evaluations) == 1
    services.judge = None
    result = await restored.ainvoke(
        Command(
            resume={
                "action": "provide_context",
                "context": "Corrected policy context",
            }
        ),
        runtime_config("halt"),
    )
    assert result["status"] == "completed"
    assert not services.governance_halt


async def test_invalid_tactical_roles_are_escalated_without_running_them():
    services = Services()
    services.packages = lambda key_result: [
        WorkPackage(
            work_package_id="wrong",
            kr_id=key_result.kr_id,
            role="backend_coder",
            task="Wrong department",
            acceptance_criteria=("done",),
        )
    ]
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert not services.executions
    assert result["auto_replans"] == 1


async def test_cancel_does_not_synthesize_a_success_report():
    services = Services()
    services.command = "cancel"
    _, result = await invoke(services)
    assert result["status"] == "cancelled"
    assert "cancelled" in result["report"]
    assert not services.executions
    assert services.planning_calls == 0


async def test_cancellation_after_worker_execution_stops_at_next_safe_boundary():
    services = Services()
    services.block = lambda *args: setattr(services, "command", "cancel")
    _, result = await invoke(services)
    assert result["status"] == "cancelled"
    assert len(services.executions) == 1
    assert not services.evaluations


async def test_model_failure_in_evaluation_escalates_as_explicit_blocker():
    services = Services()

    def malformed(*args):
        raise EscalationSignal("invalid_output", "Evaluation failed JSON validation")

    services.judge = malformed
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert result["auto_replans"] == 1
    assert result["outcomes"]["research"]["escalation"]["kind"] == "invalid_output"


async def test_failed_initial_planning_can_resume_with_context_without_phantom_krs():
    services = Services()
    requests = []

    async def fail_once(request, constitution):
        requests.append(request)
        if len(requests) == 1:
            raise EscalationSignal("provider_error", "Model unavailable")
        return services.objectives

    services.plan = fail_once
    graph, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert result["objectives"] == []
    assert result["review"]["allowed_actions"] == ["provide_context", "abort"]
    assert [event for event in services.events if event[0][0] == "planner"][-1][0][1] == "error"
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "provide_context",
                "context": "Provider connection restored",
            }
        ),
        runtime_config("test"),
    )
    assert result["status"] == "completed"
    assert len(requests) == 2
    assert "Provider connection restored" in requests[-1]
    assert [event for event in services.events if event[0][0] == "planner"][-1][0][1] == "completed"


async def test_synthesis_failure_preserves_approved_kr_ledger_and_reports_failure():
    services = Services()

    async def unavailable(*args):
        raise EscalationSignal("provider_error", "Final provider request failed")

    services.synthesize = unavailable
    _, result = await invoke(services)
    assert result["status"] == "failed"
    assert result["progress"] == {"research": "passed"}
    assert "synthesis failed" in result["report"]
    assert "artifact-research-v1-e0" in result["report"]


def test_gate_uses_evidence_criteria_score_and_constitution_not_suggested_action():
    deliverable = Deliverable(
        kr_id="test",
        department="research",
        worker_role="market_researcher",
        summary="Output",
        evidence=("Check passed",),
    )
    assert gate_approved(
        deliverable, evaluation(("done",), recommended_action="escalate_to_exec"), ("done",)
    )
    assert not gate_approved(deliverable, evaluation(("other",)), ("done",))
    assert not gate_approved(deliverable, evaluation(("done",), score=0.79), ("done",))
    assert not gate_approved(
        deliverable, evaluation(("done",), passed_constitution=False), ("done",)
    )
    assert not gate_approved(
        deliverable.model_copy(update={"evidence": ()}), evaluation(("done",)), ("done",)
    )
    assert not gate_approved(
        deliverable, evaluation(("done",), deterministic_checks_passed=False), ("done",)
    )


@pytest.mark.parametrize(
    "krs,message",
    [
        ([kr("duplicate"), kr("duplicate")], "unique"),
        ([kr("a", dependencies=("missing",))], "Unknown dependency"),
        ([kr("a", dependencies=("b",)), kr("b", dependencies=("a",))], "acyclic"),
        ([kr(str(index)) for index in range(10)], "at most nine"),
    ],
)
def test_invalid_plan_rejected_before_dispatch(krs, message):
    with pytest.raises(ValueError, match=message):
        validate_plan([objective(*krs)])


def test_review_actions_are_validated_before_resume():
    review = {"allowed_actions": ["provide_context", "revise_kr", "abort"]}
    objectives = [objective(kr())]
    with pytest.raises(ValueError, match="invalid"):
        validate_review_decision(review, {"action": "continue"}, objectives)
    with pytest.raises(ValueError, match="Context"):
        validate_review_decision(review, {"action": "provide_context", "context": " "}, objectives)
    with pytest.raises(ValueError, match="Unknown"):
        validate_review_decision(
            review, {"action": "revise_kr", "kr_id": "other", "description": "Updated"}, objectives
        )


def test_keyed_reducer_replaces_replayed_updates_and_preserves_concurrent_siblings():
    first = merge_keyed({"a": {"status": "passed"}}, {"b": {"status": "escalated"}})
    assert merge_keyed(first, {"b": {"status": "passed"}}) == {
        "a": {"status": "passed"},
        "b": {"status": "passed"},
    }
    assert len(merge_keyed(first, first)) == 2


def test_review_context_is_bounded_and_excludes_private_transcripts():
    key_results = [kr(f"kr-{index}") for index in range(9)]
    state = initial_state("bounded", "mission" * 10000, Constitution())
    state["objectives"] = [objective(*key_results).model_dump(mode="json")]
    state["progress"] = {item.kr_id: "escalated" for item in key_results}
    state["attempt_history"] = {
        f"{item.kr_id}:{attempt}": AttemptRecord(
            attempt_id=f"{item.kr_id}:{attempt}",
            kr_id=item.kr_id,
            stage="worker",
            role="market_researcher",
            execution_attempt=attempt,
            summary="界" * 2000,
            evidence=tuple("界" * 600 for _ in range(8)),
            evaluation=evaluation(
                tuple("界" * 500 + str(index) for index in range(16)), feedback="界" * 2000
            ),
        ).model_dump(mode="json")
        for item in key_results
        for attempt in range(6)
    }
    state["messages"] = [{"content": "PRIVATE TRANSCRIPT MUST NOT LEAK"}]
    packet = enrich_review_context(
        {
            "interrupt_id": "stable",
            "kind": "blocked",
            "reason": "Missing output",
            "kr_ids": list(state["progress"]),
            "allowed_actions": ["provide_context", "abort"],
        },
        state,
    )
    encoded = json.dumps(packet["context"], ensure_ascii=False).encode()
    assert len(encoded) <= 65536
    assert packet["context"]["truncated"]
    assert packet["interrupt_id"] == "stable"
    assert b"PRIVATE TRANSCRIPT" not in encoded
    assert packet["context"]["key_results"]


def test_legacy_review_surfaces_available_evidence_without_inventing_history():
    first, pending = kr("first"), kr("pending", "engineering", ("first",))
    state = {
        "run_id": "legacy",
        "user_request": "Build a researched visualization",
        "constitution": {},
        "objectives": [objective(first, pending).model_dump(mode="json")],
        "progress": {"first": "escalated", "pending": "pending"},
        "outcomes": {
            "first": {
                "kr_id": "first",
                "epoch": 3,
                "version": 1,
                "status": "escalated",
                "escalation": {
                    "kind": "constitution_violation",
                    "reason": "Worker did not produce task output",
                },
            }
        },
        "messages": [{"content": "private model conversation"}],
    }
    review = {
        "interrupt_id": "do-not-change",
        "kind": "constitution_violation",
        "reason": "Worker did not produce task output",
        "kr_ids": ["first", "pending"],
        "allowed_actions": ["provide_context", "revise_kr", "abort"],
    }
    deliverable = Deliverable(
        kr_id="first",
        department="research",
        worker_role="market_researcher",
        summary="No task output was returned",
    )
    packet = enrich_review_context(
        review,
        state,
        artifacts=[
            {
                "artifact_id": "source-receipt",
                "kr_id": "first",
                "name": "reader.json",
                "kind": "research",
                "size": 9000,
            },
            {
                "artifact_id": "empty-result",
                "kr_id": "first",
                "name": "deliverable.json",
                "kind": "deliverable",
                "epoch": 3,
                "deliverable": deliverable.model_dump(mode="json"),
            },
        ],
        events=[
            {
                "source": "harness",
                "kr_id": "first",
                "data": {
                    "evaluation": evaluation(
                        ("first accepted",), passed_constitution=False, score=0
                    ).model_dump(mode="json"),
                    "messages": "private event payload",
                },
            }
        ],
    )
    context = packet["context"]
    assert packet["interrupt_id"] == review["interrupt_id"]
    assert packet["allowed_actions"] == review["allowed_actions"]
    assert [item["kr_id"] for item in context["key_results"]] == ["first"]
    inspected = context["key_results"][0]
    assert inspected["epoch"] == 3  # Legacy record omitted epochs; outcome/receipt still prove it.
    assert inspected["evaluation"]["score"] == 0
    assert inspected["attempts"][0]["summary"] == "No task output was returned"
    assert not inspected["history_complete"]
    assert "source-receipt" in inspected["artifact_ids"]
    assert context["retry_summary"]["automatic_replans_used"] is None
    assert context["blockers"][0]["classification"] == "quality_or_execution_failure"
    assert "private" not in json.dumps(context)
    state["epochs"] = {"first": 7}
    assert enrich_review_context(review, state)["context"]["key_results"][0]["epoch"] == 7


async def test_fast_track_executes_one_actual_worker_and_one_review_without_planning_models():
    services = TriagedServices()
    _, result = await invoke(services)
    assert result["status"] == "completed"
    assert result["execution_mode"] == "FAST_TRACK"
    assert result["active_departments"] == ["engineering"]
    assert result["triage"]["source"] == "jev"
    assert services.triage_calls == 1
    assert services.planning_calls == services.synthesis_calls == 0
    assert not services.tactical_calls
    assert len(services.executions) == len(services.evaluations) == 1
    assert services.executions[0][0].role == "backend_coder"
    assert len(services.published_reports) == 1
    assert services.published_reports[0] == result["report"]
    assert "artifact-direct-1-v1-e0" in result["report"]
    assert not any(
        event[0][0] in {"planner", "research_head", "market_researcher", "data_analyst"}
        for event in services.events
    )


async def test_departmental_uses_only_selected_subgraph_and_one_final_semantic_review():
    services = TriagedServices("DEPARTMENTAL")
    services.packages = lambda key_result: [
        WorkPackage(
            work_package_id=role,
            kr_id=key_result.kr_id,
            role=role,
            task=f"Complete {role}",
            acceptance_criteria=(f"{role} finished",),
        )
        for role in ("system_architect", "backend_coder")
    ]
    _, result = await invoke(services)
    assert result["status"] == "completed"
    assert result["active_departments"] == ["engineering"]
    assert services.planning_calls == services.synthesis_calls == 0
    assert services.tactical_calls == {"direct-1": 1}
    assert len(services.executions) == 2
    assert len(services.evaluations) == 1
    assert services.max_active == 1
    assert {value[1].target_department for value in services.executions} == {"engineering"}


async def test_full_pyramid_retains_cross_department_planners_and_gates():
    services = TriagedServices(
        "FULL_PYRAMID", "engineering", kr("market"), kr("code", "engineering")
    )
    _, result = await invoke(services)
    assert result["status"] == "completed"
    assert result["active_departments"] == ["research", "engineering"]
    assert services.planning_calls == services.synthesis_calls == 1
    assert sum(services.tactical_calls.values()) == 2
    assert len(services.executions) == 2
    assert len(services.evaluations) == 4


@pytest.mark.parametrize("mode", ["FAST_TRACK", "DEPARTMENTAL"])
async def test_low_modes_allow_one_rework_without_executive_replan_reopening_limit(mode):
    services = TriagedServices(mode)
    services.judge = lambda deliverable, criteria: evaluation(
        criteria, score=0.1, feedback="Fix missing proof"
    )
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert result["revision_limit"] == 1
    assert result["auto_replans"] == 0
    assert len(services.executions) == len(services.evaluations) == 2
    assert [item[0].execution_attempt for item in services.executions] == [0, 1]
    assert result["review"]["context"]["retry_summary"]["automatic_replans_limit"] == 0
    assert result["review"]["context"]["retry_summary"]["revision_limit"] == 1


async def test_checkpoint_resume_keeps_persisted_mode_without_reclassifying():
    services = TriagedServices()
    services.command = "pause"
    saver = InMemorySaver()
    _, paused = await invoke(services, checkpointer=saver)
    assert paused["status"] == "awaiting_review"
    assert services.triage_calls == 1
    services.command = None
    restored = build_graph(services, checkpointer=saver)
    result = await restored.ainvoke(Command(resume={"action": "continue"}), runtime_config("test"))
    assert result["status"] == "completed"
    assert services.triage_calls == 1
    assert result["execution_mode"] == "FAST_TRACK"
    assert len(services.executions) == len(services.evaluations) == 1


async def test_optional_fallback_returns_to_lead_without_blocking_or_counting_partial_proof():
    services = TriagedServices("DEPARTMENTAL")
    services.packages = lambda key_result: [
        WorkPackage(
            work_package_id="optional" if not critical else "mandatory",
            kr_id=key_result.kr_id,
            role="system_architect" if not critical else "backend_coder",
            task="Produce work",
            acceptance_criteria=("Finished",),
            critical=critical,
        )
        for critical in (False, True)
    ]
    execute = services.execute

    async def with_optional_fallback(work, key_result, constitution, inputs, feedback, epoch):
        result = await execute(work, key_result, constitution, inputs, feedback, epoch)
        if not work.critical:
            return result.model_copy(
                update={
                    "fallback": True,
                    "confidence_score": 0,
                    "summary": "Incomplete optional design after timeout",
                    "artifact_ids": ("unverified-partial-note",),
                }
            )
        return result

    services.execute = with_optional_fallback
    _, result = await invoke(services)
    assert result["status"] == "completed"
    assert len(services.executions) == 2
    assert len(services.evaluations) == 1
    combined = services.evaluations[0][0]
    assert not combined.fallback
    assert "unverified-partial-note" not in combined.artifact_ids
    assert "Incomplete optional design" in combined.summary
    assert "Incomplete optional work" in result["report"]
    attempts = result["outcomes"]["direct-1"]["attempts"]
    optional = next(item for item in attempts if item["work_package_id"] == "optional")
    assert not optional["approved"]
    assert optional["evaluation"] is None
    assert optional["artifact_ids"] == ["unverified-partial-note"]


async def test_optional_fallback_alone_cannot_satisfy_mandatory_kr_gate():
    services = TriagedServices("DEPARTMENTAL")
    services.packages = lambda key_result: [
        WorkPackage(
            work_package_id="optional",
            kr_id=key_result.kr_id,
            role="backend_coder",
            task="Optional work",
            acceptance_criteria=("Finished",),
            critical=False,
        )
    ]
    execute = services.execute

    async def fallback_only(*args):
        return (await execute(*args)).model_copy(update={"fallback": True, "confidence_score": 0})

    services.execute = fallback_only
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert len(services.evaluations) == 2
    assert all(item[0].fallback for item in services.evaluations)
    assert not any(outcome["status"] == "passed" for outcome in result["outcomes"].values())


ERROR_PHASES = (
    "plan",
    "plan_work",
    "execute",
    "worker_evaluate",
    "department_evaluate",
    "synthesize",
    "publish_report",
)


def inject_service_error(services, phase, error):
    method = "evaluate" if phase.endswith("evaluate") else phase
    original = getattr(services, method)

    async def fail(*args, **kwargs):
        if phase == "department_evaluate" and not args[0].worker_role.endswith("_head"):
            return await original(*args, **kwargs)
        raise error

    setattr(services, method, fail)


@pytest.mark.parametrize("phase", ERROR_PHASES)
@pytest.mark.parametrize(
    "error_type", [KeyError, LookupError, OSError, ValueError, RunNotFoundError]
)
async def test_service_programming_and_storage_failures_escape_without_replanning(
    phase, error_type
):
    services = TriagedServices("FAST_TRACK") if phase == "publish_report" else Services()
    inject_service_error(services, phase, error_type("Unexpected producer failure"))
    with pytest.raises(error_type):
        await invoke(services)
    assert len(services.executions) <= 1


@pytest.mark.parametrize("phase", ERROR_PHASES)
async def test_explicit_service_blockers_remain_recoverable_at_each_phase(phase):
    services = TriagedServices("FAST_TRACK") if phase == "publish_report" else Services()
    inject_service_error(
        services, phase, EscalationSignal("missing_resource", "Resource unavailable")
    )
    _, result = await invoke(services)
    if phase in {"synthesize", "publish_report"}:
        assert result["status"] == "failed"
        assert "Approval evidence" in result["report"]
        assert all(status == "passed" for status in result["progress"].values())
    else:
        assert result["status"] == "awaiting_review"
        assert "Resource unavailable" in result["review"]["reason"]


@pytest.mark.parametrize("phase", ["worker_evaluate", "department_evaluate"])
async def test_only_missing_evidence_artifact_is_recoverable_at_read_only_gates(phase):
    services = Services()
    inject_service_error(services, phase, ArtifactNotFoundError("Private path must not be exposed"))
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert result["outcomes"]["research"]["escalation"]["kind"] == "artifact_missing"
    assert "unavailable for evidence review" in result["review"]["reason"]
    assert "Private path" not in json.dumps(result, default=str)


async def test_raw_execution_artifact_lookup_is_not_retried_before_unknown_side_effect_review():
    services = Services()
    inject_service_error(services, "execute", ArtifactNotFoundError("Artifact not found"))
    with pytest.raises(ArtifactNotFoundError):
        await invoke(services)
    assert not services.evaluations


@pytest.mark.parametrize("phase", ["plan", "plan_work", "execute", "evaluate", "synthesize"])
async def test_malformed_returned_contracts_are_expected_validation_failures(phase):
    services = Services()

    async def malformed(*args):
        return None

    setattr(services, phase, malformed)
    _, result = await invoke(services)
    assert result["status"] == ("failed" if phase == "synthesize" else "awaiting_review")
    reason = result["report"] if phase == "synthesize" else result["review"]["reason"]
    assert "schema validation" in reason


async def test_invalid_response_review_omits_private_model_field_values():
    services = Services()

    async def malformed(*args):
        return {"summary": "private response value", "confidence_score": "secret-provider-body"}

    services.execute = malformed
    _, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    public = json.dumps(result, default=str)
    assert "confidence_score: float_parsing" in public
    assert "private response value" not in public
    assert "secret-provider-body" not in public


@pytest.mark.parametrize("error_type", [KeyError, RunNotFoundError, OSError])
async def test_triage_does_not_hide_programming_or_storage_errors(error_type):
    services = TriagedServices()
    inject_service_error(services, "triage", error_type("Unexpected classifier failure"))
    with pytest.raises(error_type):
        await invoke(services)
    assert not services.executions


async def test_optional_triage_expected_unavailability_keeps_conservative_workflow():
    services = TriagedServices()
    inject_service_error(services, "triage", EscalationSignal("provider_error", "Classifier down"))
    _, result = await invoke(services)
    assert result["status"] == "completed"
    assert result["execution_mode"] == "FULL_PYRAMID"
    assert result["triage"]["source"] == "fallback"
    assert services.planning_calls == 1


@pytest.mark.parametrize("invalid", ["\x00", "\ud800"])
async def test_invalid_scalar_report_is_rejected_before_checkpoint_jsonb(invalid):
    services = Services()

    async def invalid_report(*args):
        return "Private report" + invalid

    services.synthesize = invalid_report
    _, result = await invoke(services)
    assert result["status"] == "failed"
    assert "Private report" not in result["report"]
    assert "Approval evidence" in result["report"]
    assert result["progress"] == {"research": "passed"}
