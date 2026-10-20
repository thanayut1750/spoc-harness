"""Automatic work cycles retain gates, operator control and bounded active state."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from test_runtime import TriagedServices, evaluation

from org_harness.models import AttemptRecord, Constitution, Escalation, EscalationSignal, RunLimits
from org_harness.runtime import build_graph, initial_state, runtime_config


class AutonomousServices(TriagedServices):
    def __init__(self, mode="FAST_TRACK"):
        super().__init__(mode, "engineering")
        self.limits = RunLimits(max_model_calls=None, worker_model_calls=None, max_tool_calls=None)
        self.run = {"limits": self.limits.model_dump(mode="json")}
        self.policy_repairs = []

    async def prepare_autonomous_repair(self, reason):
        self.policy_repairs.append(reason)
        self.governance_halt = None


async def start(services, *, constitution=None, state=None, saver=None):
    saver = saver or InMemorySaver()
    graph = build_graph(services, checkpointer=saver)
    state = state or initial_state(
        "autonomous-test", "Build verified output", constitution or Constitution()
    )
    return graph, await graph.ainvoke(state, runtime_config("autonomous-test"))


async def continue_cycle(graph, result):
    interrupts = result["__interrupt__"]
    assert all(item.value["kind"] == "automatic_cycle" for item in interrupts)
    assert result.get("review") is None
    return await graph.ainvoke(
        Command(resume={item.id: {"automatic": True} for item in interrupts}),
        runtime_config("autonomous-test"),
    )


async def test_unlimited_cycles_continue_beyond_revision_and_replan_caps_without_weakening_criteria():
    services = AutonomousServices()
    services.judge = lambda _deliverable, criteria: evaluation(
        criteria,
        passed_kr_criteria=len(services.evaluations) > 4,
        score=0.9 if len(services.evaluations) > 4 else 0,
        criterion_results=dict.fromkeys(criteria, len(services.evaluations) > 4),
        feedback="Use a different implementation; requirements remain unchanged",
    )
    graph, first = await start(services)
    original = first["objectives"]
    second = await continue_cycle(graph, first)
    completed = await continue_cycle(graph, second)
    assert completed["status"] == "completed"
    assert completed["objectives"] == original
    assert completed["automatic_cycles"] == 2
    assert completed["auto_replans"] == 2
    assert [item[-1] for item in services.executions] == [0, 0, 1, 1, 2]
    assert [item[0].execution_attempt for item in services.executions] == [0, 1, 0, 1, 0]
    assert completed["outcomes"]["direct-1"]["epoch"] == 2
    assert completed["outcomes"]["direct-1"]["status"] == "passed"


async def test_repeated_policy_blocks_keep_replanning_without_weakening_or_approving_violations():
    services = AutonomousServices()
    services.block = lambda *_: (_ for _ in ()).throw(
        EscalationSignal("constitution_violation", "Use a permitted alternative")
    )
    constitution = Constitution(prohibited_actions=("Do not disclose private material",))
    graph, first = await start(services, constitution=constitution)
    assert first["autonomous_policy_repairs"] == 1
    assert len(services.policy_repairs) == 1
    assert first["constitution"] == constitution.model_dump(mode="json")
    result = first
    for expected in (2, 3, 4):
        result = await continue_cycle(graph, result)
        assert result["autonomous_policy_repairs"] == expected
        assert result["review"] is None
        assert result["constitution"] == constitution.model_dump(mode="json")
        assert result["outcomes"]["direct-1"]["status"] != "passed"
    services.block = None
    completed = await continue_cycle(graph, result)
    assert completed["status"] == "completed"
    assert completed["constitution"] == constitution.model_dump(mode="json")
    assert len(services.executions) == 5 and len(services.evaluations) == 1


async def test_a_policy_repair_can_complete_only_after_the_normal_acceptance_gate_passes():
    services = AutonomousServices()

    def blocked_once(_work, _kr, epoch):
        if epoch == 0:
            raise EscalationSignal("constitution_violation", "Choose a compliant implementation")

    services.block = blocked_once
    graph, first = await start(services)
    completed = await continue_cycle(graph, first)
    assert completed["status"] == "completed"
    assert len(services.policy_repairs) == 1 and len(services.evaluations) == 1
    assert completed["outcomes"]["direct-1"]["evaluation"]["passed_constitution"]


async def test_planning_repair_receives_bounded_blocker_context_without_changing_the_mission():
    services = AutonomousServices("FULL_PYRAMID")
    original = services.plan
    requests = []

    async def plan(request, constitution):
        requests.append((request, constitution))
        if len(requests) == 1:
            raise EscalationSignal("invalid_plan", "Dependency KR missing; use an acyclic plan")
        return await original(request, constitution)

    services.plan = plan
    graph, first = await start(services)
    completed = await continue_cycle(graph, first)
    assert completed["status"] == "completed" and len(requests) == 2
    assert requests[0][0] == completed["user_request"] == "Build verified output"
    assert "Dependency KR missing; use an acyclic plan" in requests[1][0]
    assert requests[0][1] == requests[1][1]
    assert completed["planning_feedback"] == ""


async def test_unknown_command_is_never_blindly_retried_or_sent_for_human_approval():
    services = AutonomousServices()
    services.block = lambda *_: (_ for _ in ()).throw(
        EscalationSignal("unknown_operation", "Unknown side effects")
    )
    _, result = await start(services)
    assert result["status"] == "failed"
    assert result["review"] is None and not result.get("__interrupt__")
    assert len(services.executions) == 1


async def test_reconciled_command_receipts_allow_fresh_inspection_and_repair_without_retry_approval():
    services = AutonomousServices()
    services.run["autonomous_command_recoveries"] = [
        {
            "operation_id": "old-op",
            "result": {"process_state": "stopped", "artifact_ids": ["receipt"]},
        }
    ]
    services.block = lambda _work, _kr, epoch: (
        (_ for _ in ()).throw(EscalationSignal("unknown_operation", "Inspect interrupted work"))
        if epoch == 0
        else None
    )
    graph, first = await start(services)
    assert "Do not repeat the interrupted command" in first["feedback"]["direct-1"]
    completed = await continue_cycle(graph, first)
    assert completed["status"] == "completed"
    assert services.resolved_operations == 0


async def test_manual_pause_and_cancel_remain_operator_controls_in_unlimited_mode():
    services = AutonomousServices()
    services.command = "pause"
    graph, paused = await start(services)
    assert paused["__interrupt__"][0].value["kind"] == "manual_pause"
    assert not services.executions
    services.command = None
    finished = await graph.ainvoke(
        Command(resume={"action": "continue", "interrupt_id": "test"}),
        runtime_config("autonomous-test"),
    )
    assert finished["status"] == "completed"
    cancelled = AutonomousServices()
    cancelled.command = "cancel"
    _, result = await start(cancelled)
    assert result["status"] == "cancelled" and not cancelled.executions


async def test_one_finite_cap_preserves_the_existing_review_boundary():
    services = AutonomousServices()
    services.limits = services.limits.model_copy(update={"max_tool_calls": 200})
    services.block = lambda *_: (_ for _ in ()).throw(
        EscalationSignal("worker_timeout", "Bounded invocation expired")
    )
    _, result = await start(services)
    assert result["status"] == "awaiting_review"
    assert result["__interrupt__"][0].value["kind"] == "blocked"


@pytest.mark.parametrize("phase", ["plan", "finish"])
async def test_planning_and_reporting_provider_failures_yield_and_resume_the_correct_boundary(
    phase,
):
    services = AutonomousServices("FULL_PYRAMID")
    original = services.plan if phase == "plan" else services.synthesize
    calls = 0

    async def transient(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise EscalationSignal("provider_error", "Provider temporarily unavailable")
        return await original(*args)

    setattr(services, "plan" if phase == "plan" else "synthesize", transient)
    graph, first = await start(services)
    completed = await continue_cycle(graph, first)
    assert completed["status"] == "completed" and calls == 2
    assert len(services.executions) == 1
    assert all(outcome["status"] == "passed" for outcome in completed["outcomes"].values())


async def test_active_checkpoint_history_remains_bounded_across_many_epochs():
    services = AutonomousServices()
    services.block = lambda *_: (_ for _ in ()).throw(
        EscalationSignal("worker_timeout", "Continue another work cycle")
    )
    state = initial_state("autonomous-test", "Build verified output", Constitution())
    state["attempt_history"] = {
        f"old-{index}": AttemptRecord(
            attempt_id=f"old-{index}",
            kr_id="direct-1",
            epoch=index,
            stage="worker",
            role="backend_coder",
        ).model_dump(mode="json")
        for index in range(300)
    }
    state["escalations"] = {
        f"old-{index}": Escalation(
            escalation_id=f"old-{index}",
            kr_id="direct-1",
            kind="blocked",
            reason="Old failure",
            resolved=True,
        ).model_dump(mode="json")
        for index in range(300)
    }
    _, first = await start(services, state=state)
    assert len(first["attempt_history"]) <= 128
    assert len(first["escalations"]) <= 64
    assert first["review"] is None
