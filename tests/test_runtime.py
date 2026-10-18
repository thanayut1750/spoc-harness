"""Behavioral graph tests run genuine nested graphs with scripted model services."""

import asyncio
from collections import Counter

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from org_harness.models import (
    Constitution,
    Deliverable,
    EscalationSignal,
    Evaluation,
    KeyResult,
    StrategicObjective,
    WorkPackage,
)
from org_harness.runtime import (
    build_graph,
    department_context,
    gate_approved,
    initial_state,
    merge_keyed,
    runtime_config,
    validate_plan,
    validate_review_decision,
)


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
        assert all(o.status == "passed" for o in outcomes)
        return "The mission was completed with approved evidence."

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
        "work_index",
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
    assert result["epochs"] == {"research": 1}
    assert result["review"]["kind"] == "blocked"
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
    assert services.planning_calls == 1
    assert all(escalation["resolved"] for escalation in result["escalations"].values())


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
        feedback="Prohibited action detected",
    )
    graph, result = await invoke(services)
    assert result["status"] == "awaiting_review"
    assert result["auto_replans"] == 0
    assert result["review"]["kind"] == "constitution_violation"
    assert len(services.executions) == 2
    assert not any(status == "passed" for status in result["progress"].values())
    result = await graph.ainvoke(Command(resume={"action": "abort"}), runtime_config("test"))
    assert result["status"] == "cancelled"
    assert services.planning_calls == 1
    assert len(services.executions) == 2


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
    assert len(services.evaluations) == 2


async def test_durable_constitution_halt_survives_crash_before_outcome_checkpoint():
    services = Services()
    services.judge = lambda deliverable, criteria: evaluation(
        criteria,
        passed_constitution=False,
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
