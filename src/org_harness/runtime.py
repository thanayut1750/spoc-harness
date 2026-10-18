"""Durable organizational workflow with explicit, private graph boundaries.

The executive stores only validated JSON contracts. Department and worker
subgraphs inherit the parent's checkpointer for one invocation; neither receives
the parent's conversation history. Every gate and lifecycle transition is
deterministic even though planning, execution, and judging are model services.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from org_harness.models import (
    Constitution,
    Deliverable,
    DepartmentOutcome,
    Escalation,
    EscalationSignal,
    Evaluation,
    KeyResult,
    ReviewDecision,
    StrategicObjective,
    WorkPackage,
)

JSON = dict[str, Any]
ROLES = {
    "research": {"market_researcher", "data_analyst"},
    "engineering": {"system_architect", "backend_coder"},
}


class RuntimeServices(Protocol):
    """Model and host integration seam; implementations are scoped to one run."""

    async def plan(
        self, user_request: str, constitution: Constitution
    ) -> list[StrategicObjective]: ...

    async def plan_work(
        self,
        kr: KeyResult,
        constitution: Constitution,
        inputs: list[Deliverable],
        feedback: str,
    ) -> list[WorkPackage]: ...

    async def execute(
        self,
        work: WorkPackage,
        kr: KeyResult,
        constitution: Constitution,
        inputs: list[Deliverable],
        feedback: str,
        epoch: int,
    ) -> Deliverable: ...

    async def evaluate(
        self, deliverable: Deliverable, criteria: tuple[str, ...], constitution: Constitution
    ) -> Evaluation: ...

    async def synthesize(
        self,
        user_request: str,
        objectives: list[StrategicObjective],
        outcomes: list[DepartmentOutcome],
    ) -> str: ...

    async def emit(self, agent_id: str, activity: str, summary: str, **data: Any) -> None: ...

    async def control(self) -> str | None: ...

    async def notes(self, agent_id: str) -> list[str]: ...


def merge_keyed(left: dict | None, right: dict | None) -> dict:
    """Keyed replacement makes replay/fanout idempotent without losing peers."""
    return {**(left or {}), **(right or {})}


class ExecutiveState(TypedDict, total=False):
    run_id: str
    user_request: str
    constitution: JSON
    objectives: list[JSON]
    progress: Annotated[dict[str, str], merge_keyed]
    outcomes: Annotated[dict[str, JSON], merge_keyed]
    escalations: Annotated[dict[str, JSON], merge_keyed]
    epochs: dict[str, int]
    feedback: dict[str, str]
    auto_replans: int
    dispatches: list[JSON]
    review: JSON | None
    report: str
    status: str
    route: str


class DepartmentState(TypedDict, total=False):
    run_id: str
    constitution: JSON
    kr: JSON
    epoch: int
    inputs: list[JSON]
    feedback: str
    work_packages: list[JSON]
    work_index: int
    revisions: int
    accepted: list[JSON]
    worker_result: JSON
    deliverable: JSON
    evaluation: JSON
    outcome: JSON
    route: str


class WorkerState(TypedDict, total=False):
    run_id: str
    constitution: JSON
    kr: JSON
    work: JSON
    epoch: int
    inputs: list[JSON]
    feedback: str
    deliverable: JSON
    evaluation: JSON
    escalation: JSON
    approved: bool


def initial_state(
    run_id: str, user_request: str, constitution: Constitution | Mapping[str, Any]
) -> ExecutiveState:
    return {
        "run_id": run_id,
        "user_request": user_request,
        "constitution": Constitution.model_validate(constitution).model_dump(mode="json"),
        "objectives": [],
        "progress": {},
        "outcomes": {},
        "escalations": {},
        "epochs": {},
        "feedback": {},
        "auto_replans": 0,
        "dispatches": [],
        "review": None,
        "report": "",
        "status": "running",
    }


def runtime_config(run_id: str) -> RunnableConfig:
    # Bounded even with nine KRs, ten configured revisions, and manual recovery.
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 1000}


def validate_plan(objectives: Sequence[StrategicObjective | JSON]) -> list[StrategicObjective]:
    parsed = [StrategicObjective.model_validate(item) for item in objectives]
    if not 1 <= len(parsed) <= 3:
        raise ValueError("A plan must contain 1–3 objectives")
    ids = [objective.objective_id for objective in parsed]
    if len(ids) != len(set(ids)):
        raise ValueError("Objective IDs must be unique")
    krs = [kr for objective in parsed for kr in objective.key_results]
    if not 1 <= len(krs) <= 9:
        raise ValueError("A plan must contain at most nine key results")
    by_id = {kr.kr_id: kr for kr in krs}
    if len(by_id) != len(krs):
        raise ValueError("Key result IDs must be unique")
    if any(
        not kr.kr_id.strip()
        or not kr.description.strip()
        or not all(criterion.strip() for criterion in kr.acceptance_criteria)
        for kr in krs
    ):
        raise ValueError("Key result identifiers, descriptions, and criteria must not be empty")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(kr_id: str) -> None:
        if kr_id in visiting:
            raise ValueError("Key result dependencies must form an acyclic graph")
        if kr_id in visited:
            return
        visiting.add(kr_id)
        for dependency in by_id[kr_id].dependency_kr_ids:
            if dependency not in by_id:
                raise ValueError(f"Unknown dependency: {dependency}")
            visit(dependency)
        visiting.remove(kr_id)
        visited.add(kr_id)

    for kr_id in by_id:
        visit(kr_id)
    return parsed


def gate_approved(
    deliverable: Deliverable, evaluation: Evaluation, criteria: tuple[str, ...]
) -> bool:
    """A judge's routing recommendation never overrides evidence or policy."""
    return (
        evaluation.passed_constitution
        and evaluation.passed_kr_criteria
        and evaluation.score >= 0.8
        and getattr(evaluation, "deterministic_checks_passed", True)
        and all(evaluation.criterion_results.get(criterion) is True for criterion in criteria)
        and bool(deliverable.summary.strip())
        and (any(item.strip() for item in deliverable.evidence) or bool(deliverable.artifact_ids))
    )


def _krs(state: ExecutiveState) -> dict[str, KeyResult]:
    return {
        kr.kr_id: kr
        for objective in state.get("objectives", [])
        for kr in StrategicObjective.model_validate(objective).key_results
    }


def _current_outcomes(state: ExecutiveState) -> dict[str, DepartmentOutcome]:
    krs = _krs(state)
    result = {}
    for kr_id, raw in state.get("outcomes", {}).items():
        outcome = DepartmentOutcome.model_validate(raw)
        if (
            kr_id in krs
            and outcome.version == krs[kr_id].version
            and outcome.epoch == state.get("epochs", {}).get(kr_id, 0)
        ):
            result[kr_id] = outcome
    return result


def department_context(state: ExecutiveState, kr: KeyResult) -> DepartmentState:
    """Bounded handoff: only approved dependencies, never parent messages."""
    outcomes = _current_outcomes(state)
    inputs = [
        deliverable.model_dump(mode="json")
        for dependency in kr.dependency_kr_ids
        if outcomes[dependency].status == "passed"
        and (deliverable := outcomes[dependency].deliverable) is not None
    ]
    return {
        "run_id": state["run_id"],
        "constitution": state["constitution"],
        "kr": kr.model_dump(mode="json"),
        "epoch": state.get("epochs", {}).get(kr.kr_id, 0),
        "inputs": inputs,
        "feedback": state.get("feedback", {}).get(kr.kr_id, "")[-12000:],
        "revisions": 0,
        "accepted": [],
        "work_index": 0,
    }


def worker_context(state: DepartmentState, work: WorkPackage) -> WorkerState:
    return {
        "run_id": state["run_id"],
        "constitution": state["constitution"],
        "kr": state["kr"],
        "work": work.model_dump(mode="json"),
        "epoch": state["epoch"],
        "inputs": state.get("inputs", []) + state.get("accepted", []),
        "feedback": state.get("feedback", "")[-12000:],
    }


def validate_review_decision(
    review: Mapping[str, Any],
    decision: Mapping[str, Any],
    objectives: Sequence[StrategicObjective | JSON],
) -> JSON:
    parsed = ReviewDecision.model_validate({"interrupt_id": "runtime", **decision})
    data = parsed.model_dump(mode="json", exclude_none=True)
    if parsed.action not in review.get("allowed_actions", []):
        raise ValueError(f"Action {parsed.action!r} is invalid for this review")
    krs = {
        kr.kr_id: kr
        for item in objectives
        for kr in StrategicObjective.model_validate(item).key_results
    }
    if parsed.kr_id and parsed.kr_id not in krs:
        raise ValueError("Unknown key result")
    if parsed.action == "provide_context" and not (parsed.context or "").strip():
        raise ValueError("Context must not be empty")
    if parsed.action == "revise_kr":
        if not parsed.kr_id or not (parsed.description or parsed.acceptance_criteria):
            raise ValueError("A KR revision requires kr_id and new description or criteria")
        if parsed.description is not None and not parsed.description.strip():
            raise ValueError("KR description must not be empty")
        if parsed.acceptance_criteria is not None and (
            not parsed.acceptance_criteria or not all(c.strip() for c in parsed.acceptance_criteria)
        ):
            raise ValueError("Acceptance criteria must not be empty")
    return data


def _escalation(state: DepartmentState | WorkerState, kind: str, reason: str) -> Escalation:
    kr = KeyResult.model_validate(state["kr"])
    return Escalation(
        escalation_id=f"{state['run_id']}:{kr.kr_id}:v{kr.version}:e{state['epoch']}:{kind}",
        kr_id=kr.kr_id,
        kind=kind,
        reason=reason,
    )


def _outcome(
    state: DepartmentState,
    *,
    escalation: Escalation | None = None,
    deliverable: Deliverable | None = None,
    evaluation: Evaluation | None = None,
) -> JSON:
    kr = KeyResult.model_validate(state["kr"])
    return DepartmentOutcome(
        kr_id=kr.kr_id,
        version=kr.version,
        epoch=state["epoch"],
        status="escalated" if escalation else "passed",
        escalation=escalation,
        deliverable=deliverable,
        evaluation=evaluation,
    ).model_dump(mode="json")


def _review_payload(kind: str, reason: str, kr_ids: list[str]) -> JSON:
    actions = ["provide_context", "revise_kr", "abort"]
    if kind == "manual_pause":
        actions = ["continue", "abort"]
    elif kind == "unknown_operation":
        actions = ["retry_operation", "abort"]
    return {"kind": kind, "reason": reason, "kr_ids": kr_ids, "allowed_actions": actions}


def build_graph(services: RuntimeServices, *, checkpointer: Any = None, store: Any = None):
    """Build root and per-invocation child graphs using the supplied durable stores."""
    halted: dict[str, asyncio.Event] = {}

    def halt(run_id: str) -> asyncio.Event:
        return halted.setdefault(run_id, asyncio.Event())

    async def mark_halted(
        state: DepartmentState | WorkerState | ExecutiveState, reason: str
    ) -> None:
        halt(state["run_id"]).set()
        persist = getattr(services, "halt_for_review", None)
        if persist is not None:
            await persist("constitution_violation", reason)

    async def boundary(state: DepartmentState | WorkerState) -> Escalation | None:
        control = await services.control()
        if control == "cancel":
            return _escalation(state, "cancelled", "Run cancellation requested")
        if control == "suspend" or halt(state["run_id"]).is_set():
            return _escalation(
                state, "suspended", "Dispatch suspended after constitution violation"
            )
        return None

    async def execute(state: WorkerState) -> JSON:
        if escalation := await boundary(state):
            return {"escalation": escalation.model_dump(mode="json"), "approved": False}
        kr = KeyResult.model_validate(state["kr"])
        work = WorkPackage.model_validate(state["work"])
        notes = await services.notes(work.role)
        feedback = "\n".join([state.get("feedback", ""), *notes])[-12000:]
        await services.emit(
            f"{kr.target_department}_head",
            "planning",
            f"Assign {work.work_package_id[:128]}",
            kr_id=kr.kr_id,
            target_agent_id=work.role,
        )
        await services.emit(work.role, "executing", work.task, kr_id=kr.kr_id)
        try:
            result = Deliverable.model_validate(
                await services.execute(
                    work,
                    kr,
                    Constitution.model_validate(state["constitution"]),
                    [Deliverable.model_validate(item) for item in state.get("inputs", [])],
                    feedback,
                    state["epoch"],
                )
            )
        except (ValueError, EscalationSignal) as exc:
            kind = exc.kind if isinstance(exc, EscalationSignal) else "invalid_output"
            if kind == "constitution_violation":
                await mark_halted(state, str(exc))
            await services.emit(work.role, "error", str(exc), kr_id=kr.kr_id, kind=kind)
            return {
                "escalation": _escalation(state, kind, str(exc)).model_dump(mode="json"),
                "approved": False,
            }
        if (
            result.kr_id != kr.kr_id
            or result.department != kr.target_department
            or result.worker_role != work.role
        ):
            return {
                "escalation": _escalation(
                    state, "invalid_output", "Worker returned a deliverable for another assignment"
                ).model_dump(mode="json"),
                "approved": False,
            }
        await services.emit(
            work.role,
            "completed",
            "Specialist deliverable submitted",
            kr_id=kr.kr_id,
            artifact_ids=list(result.artifact_ids),
            target_agent_id=f"{kr.target_department}_gatekeeper",
        )
        return {"deliverable": result.model_dump(mode="json")}

    async def worker_gate(state: WorkerState) -> JSON:
        if state.get("escalation"):
            return {}
        if escalation := await boundary(state):
            return {"escalation": escalation.model_dump(mode="json"), "approved": False}
        work = WorkPackage.model_validate(state["work"])
        deliverable = Deliverable.model_validate(state["deliverable"])
        await services.emit(
            f"{deliverable.department}_gatekeeper",
            "reviewing",
            f"Review {work.work_package_id}",
            kr_id=deliverable.kr_id,
        )
        try:
            evaluation = Evaluation.model_validate(
                await services.evaluate(
                    deliverable,
                    work.acceptance_criteria,
                    Constitution.model_validate(state["constitution"]),
                )
            )
        except (ValueError, EscalationSignal) as exc:
            kind = exc.kind if isinstance(exc, EscalationSignal) else "invalid_output"
            if kind == "constitution_violation":
                await mark_halted(state, str(exc))
            return {
                "escalation": _escalation(state, kind, str(exc)).model_dump(mode="json"),
                "approved": False,
            }
        update = {
            "evaluation": evaluation.model_dump(mode="json"),
            "approved": gate_approved(deliverable, evaluation, work.acceptance_criteria),
        }
        if not evaluation.passed_constitution:
            await mark_halted(state, evaluation.feedback)
            update["escalation"] = _escalation(
                state, "constitution_violation", evaluation.feedback
            ).model_dump(mode="json")
        await services.emit(
            f"{deliverable.department}_gatekeeper",
            "completed" if update["approved"] else "error",
            f"Work package {work.work_package_id}: "
            + ("approved" if update["approved"] else "rejected"),
            kr_id=deliverable.kr_id,
            evaluation=evaluation.model_dump(mode="json"),
        )
        return update

    worker_builder = StateGraph(WorkerState)
    worker_builder.add_node("execute", execute)
    worker_builder.add_node("gate", worker_gate)
    worker_builder.add_edge(START, "execute")
    worker_builder.add_edge("execute", "gate")
    worker_builder.add_edge("gate", END)
    worker = worker_builder.compile(checkpointer=None)

    async def plan_work(state: DepartmentState) -> JSON:
        if escalation := await boundary(state):
            return {"outcome": _outcome(state, escalation=escalation), "route": "done"}
        kr = KeyResult.model_validate(state["kr"])
        notes = await services.notes(f"{kr.target_department}_head")
        feedback = "\n".join([state.get("feedback", ""), *notes])[-12000:]
        await services.emit(
            f"{kr.target_department}_head", "planning", kr.description, kr_id=kr.kr_id
        )
        try:
            packages = [
                WorkPackage.model_validate(item)
                for item in await services.plan_work(
                    kr,
                    Constitution.model_validate(state["constitution"]),
                    [Deliverable.model_validate(item) for item in state.get("inputs", [])],
                    feedback,
                )
            ]
            if not 1 <= len(packages) <= 4:
                raise ValueError("A tactical plan needs 1–4 work packages")
            if len({p.work_package_id for p in packages}) != len(packages):
                raise ValueError("Work package IDs must be unique within a tactical plan")
            if any(
                p.kr_id != kr.kr_id or p.role not in ROLES[kr.target_department] for p in packages
            ):
                raise ValueError("Tactical plan contains an invalid assignment or specialist role")
        except (ValueError, EscalationSignal) as exc:
            kind = exc.kind if isinstance(exc, EscalationSignal) else "invalid_plan"
            if kind == "constitution_violation":
                await mark_halted(state, str(exc))
            return {
                "outcome": _outcome(state, escalation=_escalation(state, kind, str(exc))),
                "route": "done",
            }
        return {
            "work_packages": [p.model_dump(mode="json") for p in packages],
            "work_index": 0,
            "accepted": [],
            "feedback": feedback,
            "route": "worker",
        }

    async def run_worker(state: DepartmentState, config: RunnableConfig) -> JSON:
        work = WorkPackage.model_validate(state["work_packages"][state["work_index"]])
        result = await worker.ainvoke(worker_context(state, work), config)
        # Do not copy worker transcript/private channels into department or executive state.
        return {
            "worker_result": {
                key: result[key]
                for key in ("deliverable", "evaluation", "escalation", "approved")
                if key in result
            }
        }

    async def collect_worker(state: DepartmentState) -> JSON:
        result = state["worker_result"]
        if result.get("escalation"):
            return {
                "outcome": _outcome(
                    state, escalation=Escalation.model_validate(result["escalation"])
                ),
                "route": "done",
            }
        if result.get("approved"):
            accepted = [*state.get("accepted", []), result["deliverable"]]
            index = state["work_index"] + 1
            return {
                "accepted": accepted,
                "work_index": index,
                "route": "worker" if index < len(state["work_packages"]) else "gate",
            }
        evaluation = Evaluation.model_validate(result["evaluation"])
        return revision(state, evaluation.feedback, "worker")

    def revision(state: DepartmentState, feedback: str, route: str) -> JSON:
        constitution = Constitution.model_validate(state["constitution"])
        if state.get("revisions", 0) >= constitution.max_revision_loops:
            return {
                "outcome": _outcome(
                    state, escalation=_escalation(state, "revision_exhausted", feedback)
                ),
                "route": "done",
            }
        return {
            "revisions": state.get("revisions", 0) + 1,
            "feedback": feedback[-12000:],
            "route": route,
        }

    async def department_gate(state: DepartmentState) -> JSON:
        if escalation := await boundary(state):
            return {"outcome": _outcome(state, escalation=escalation), "route": "done"}
        kr = KeyResult.model_validate(state["kr"])
        accepted = [Deliverable.model_validate(raw) for raw in state["accepted"]]
        combined = Deliverable(
            kr_id=kr.kr_id,
            department=kr.target_department,
            worker_role=f"{kr.target_department}_head",
            summary="\n\n".join(item.summary for item in accepted),
            artifact_ids=tuple(dict.fromkeys(a for item in accepted for a in item.artifact_ids)),
            evidence=tuple(dict.fromkeys(e for item in accepted for e in item.evidence)),
            confidence_score=min(item.confidence_score for item in accepted),
        )
        await services.emit(
            f"{kr.target_department}_gatekeeper",
            "reviewing",
            f"Review complete KR {kr.kr_id}",
            kr_id=kr.kr_id,
        )
        try:
            evaluation = Evaluation.model_validate(
                await services.evaluate(
                    combined,
                    kr.acceptance_criteria,
                    Constitution.model_validate(state["constitution"]),
                )
            )
        except (ValueError, EscalationSignal) as exc:
            kind = exc.kind if isinstance(exc, EscalationSignal) else "invalid_output"
            if kind == "constitution_violation":
                await mark_halted(state, str(exc))
            return {
                "outcome": _outcome(state, escalation=_escalation(state, kind, str(exc))),
                "route": "done",
            }
        approved = gate_approved(combined, evaluation, kr.acceptance_criteria)
        if not evaluation.passed_constitution:
            await mark_halted(state, evaluation.feedback)
        await services.emit(
            f"{kr.target_department}_gatekeeper",
            "completed" if approved else "error",
            f"Complete KR {kr.kr_id}: " + ("approved" if approved else "rejected"),
            kr_id=kr.kr_id,
            evaluation=evaluation.model_dump(mode="json"),
        )
        if not evaluation.passed_constitution:
            return {
                "outcome": _outcome(
                    state,
                    escalation=_escalation(state, "constitution_violation", evaluation.feedback),
                    deliverable=combined,
                    evaluation=evaluation,
                ),
                "route": "done",
            }
        if approved:
            await services.emit(
                f"{kr.target_department}_head",
                "completed",
                f"KR {kr.kr_id} passed",
                kr_id=kr.kr_id,
                target_agent_id="executive",
            )
            return {
                "outcome": _outcome(state, deliverable=combined, evaluation=evaluation),
                "route": "done",
            }
        return revision(state, evaluation.feedback, "plan")

    department_builder = StateGraph(DepartmentState)
    department_builder.add_node("plan", plan_work)
    department_builder.add_node("worker", run_worker)
    department_builder.add_node("collect", collect_worker)
    department_builder.add_node("gate", department_gate)
    department_builder.add_edge(START, "plan")
    department_builder.add_conditional_edges(
        "plan", lambda state: state["route"], {"worker": "worker", "done": END}
    )
    department_builder.add_edge("worker", "collect")
    department_builder.add_conditional_edges(
        "collect", lambda state: state["route"], {"worker": "worker", "gate": "gate", "done": END}
    )
    department_builder.add_conditional_edges(
        "gate", lambda state: state["route"], {"plan": "plan", "done": END}
    )
    department = department_builder.compile(checkpointer=None)

    async def plan(state: ExecutiveState) -> JSON:
        if state.get("objectives"):
            return {}
        if await services.control() == "cancel":
            return {"status": "cancelled", "route": "finish", "review": None}
        await services.emit("planner", "planning", "Create Strategic Pyramid")
        notes = await services.notes("planner")
        request = "\n".join([state["user_request"], *notes])
        try:
            objectives = validate_plan(
                await services.plan(request, Constitution.model_validate(state["constitution"]))
            )
        except (ValueError, EscalationSignal) as exc:
            kind = exc.kind if isinstance(exc, EscalationSignal) else "invalid_plan"
            if kind == "constitution_violation":
                await mark_halted(state, str(exc))
            await services.emit("planner", "error", str(exc), kind=kind)
            review = _review_payload(kind, str(exc), [])
            review["allowed_actions"] = ["provide_context", "abort"]
            return {"review": review, "status": "awaiting_review", "route": "review"}
        krs = [kr for obj in objectives for kr in obj.key_results]
        await services.emit(
            "planner",
            "completed",
            "Strategic Pyramid validated",
            objectives=len(objectives),
            key_results=len(krs),
        )
        return {
            "objectives": [o.model_dump(mode="json") for o in objectives],
            "epochs": {kr.kr_id: 0 for kr in krs},
            "progress": {kr.kr_id: "pending" for kr in krs},
            "auto_replans": state.get("auto_replans", 0),
            "route": "coordinate",
        }

    async def coordinate(state: ExecutiveState) -> JSON:
        control = await services.control()
        if control == "cancel":
            return {"status": "cancelled", "route": "finish", "review": None}
        if control == "suspend":
            outcomes = _current_outcomes(state)
            blocked_ids = [
                key
                for key in _krs(state)
                if key not in outcomes or outcomes[key].status != "passed"
            ]
            reasons = [
                outcome.escalation.reason
                for outcome in outcomes.values()
                if outcome.escalation and outcome.escalation.kind == "constitution_violation"
            ]
            return {
                "status": "awaiting_review",
                "route": "review",
                "review": _review_payload(
                    "constitution_violation",
                    "\n".join(reasons)
                    or "Execution was suspended after a constitution violation; inspect recorded evidence.",
                    blocked_ids,
                ),
            }
        if control == "pause":
            return {
                "status": "awaiting_review",
                "route": "review",
                "review": _review_payload("manual_pause", "Pause requested", []),
            }
        outcomes = _current_outcomes(state)
        blocked = [o for o in outcomes.values() if o.status != "passed"]
        if blocked:
            escalations = [o.escalation for o in blocked if o.escalation]
            violation = next((e for e in escalations if e.kind == "constitution_violation"), None)
            unknown = next((e for e in escalations if e.kind == "unknown_operation"), None)
            cancelled = next((e for e in escalations if e.kind == "cancelled"), None)
            if cancelled:
                return {"status": "cancelled", "route": "finish", "review": None}
            if not violation and not unknown and state.get("auto_replans", 0) == 0:
                return {"route": "replan"}
            kind = (
                "constitution_violation"
                if violation
                else "unknown_operation"
                if unknown
                else "blocked"
            )
            reason = "\n".join(e.reason for e in escalations) or "Department execution failed"
            return {
                "status": "awaiting_review",
                "route": "review",
                "review": _review_payload(kind, reason, [o.kr_id for o in blocked]),
            }
        krs = _krs(state)
        passed = {key for key, value in outcomes.items() if value.status == "passed"}
        if krs and len(passed) == len(krs):
            return {"route": "finish", "status": "completed", "review": None}
        selected: list[KeyResult] = []
        departments: set[str] = set()
        for kr in krs.values():
            if kr.kr_id not in passed and set(kr.dependency_kr_ids) <= passed:
                if kr.target_department not in departments:
                    selected.append(kr)
                    departments.add(kr.target_department)
                if len(selected) == 2:
                    break
        if not selected:
            return {
                "status": "failed",
                "route": "finish",
                "report": "No runnable key results; dependency scheduling cannot advance.",
            }
        halt(state["run_id"]).clear()
        await services.emit("executive", "planning", f"Dispatch {len(selected)} ready key results")
        for kr in selected:
            await services.emit(
                "executive",
                "planning",
                f"Dispatch KR {kr.kr_id}",
                kr_id=kr.kr_id,
                target_agent_id=f"{kr.target_department}_head",
            )
        notes = await services.notes("executive")
        dispatches = [department_context(state, kr) for kr in selected]
        if notes:
            dispatches = [
                {**item, "feedback": "\n".join([item["feedback"], *notes])[-12000:]}
                for item in dispatches
            ]
        return {
            "route": "dispatch",
            "status": "running",
            "review": None,
            "dispatches": dispatches,
            "progress": {kr.kr_id: "running" for kr in selected},
        }

    def route(state: ExecutiveState):
        if state["route"] == "dispatch":
            return [Send("department", dispatch) for dispatch in state["dispatches"]]
        return state["route"]

    async def run_department(state: DepartmentState, config: RunnableConfig) -> JSON:
        result = await department.ainvoke(state, config)
        outcome = DepartmentOutcome.model_validate(result["outcome"])
        update: JSON = {
            "outcomes": {outcome.kr_id: outcome.model_dump(mode="json")},
            "progress": {outcome.kr_id: outcome.status},
        }
        if outcome.escalation:
            update["escalations"] = {
                outcome.escalation.escalation_id: outcome.escalation.model_dump(mode="json")
            }
        return update

    def reset_epochs(state: ExecutiveState, kr_ids: set[str], context: str) -> JSON:
        epochs = dict(state.get("epochs", {}))
        feedback = dict(state.get("feedback", {}))
        escalations = {}
        for kr_id in kr_ids:
            epochs[kr_id] = epochs.get(kr_id, 0) + 1
            feedback[kr_id] = context[-12000:]
        for key, raw in state.get("escalations", {}).items():
            if raw["kr_id"] in kr_ids and not raw.get("resolved"):
                escalations[key] = {**raw, "resolved": True}
        return {
            "epochs": epochs,
            "feedback": feedback,
            "escalations": escalations,
            "progress": {key: "pending" for key in kr_ids},
            "status": "running",
            "review": None,
        }

    async def replan(state: ExecutiveState) -> JSON:
        blocked = {
            key: value
            for key, value in _current_outcomes(state).items()
            if value.status != "passed"
        }
        feedback = (
            "Executive replan: reconsider tactics and ordering. Preserve all acceptance criteria.\n"
        )
        feedback += "\n".join(o.escalation.reason for o in blocked.values() if o.escalation)
        await services.emit("executive", "planning", "Automatic executive replan", replan=1)
        return {**reset_epochs(state, set(blocked), feedback), "auto_replans": 1}

    async def human_review(state: ExecutiveState) -> JSON:
        # This node deliberately performs no side effects before interrupt.
        decision = validate_review_decision(
            state["review"] or {}, interrupt(state["review"]), state.get("objectives", [])
        )
        resolve_review = getattr(services, "resolve_review", None)
        if resolve_review is not None:
            await resolve_review(decision)
        if decision["action"] == "abort":
            return {"status": "cancelled", "review": None, "route": "finish"}
        if decision["action"] == "continue":
            return {"status": "running", "review": None, "route": "coordinate"}
        if not state.get("objectives"):
            # A planning blocker can be repaired without replaying already completed work.
            return {
                "user_request": state["user_request"]
                + "\n\nHuman context: "
                + decision.get("context", ""),
                "review": None,
                "status": "running",
                "route": "plan",
            }
        ids = set((state["review"] or {}).get("kr_ids", []))
        if decision.get("kr_id"):
            ids = {decision["kr_id"]}
        update: JSON = {}
        if decision["action"] == "revise_kr":
            target = decision["kr_id"]
            objectives = [StrategicObjective.model_validate(o) for o in state["objectives"]]
            revised = []
            for objective in objectives:
                krs = tuple(
                    kr.model_copy(
                        update={
                            "description": decision.get("description", kr.description),
                            "acceptance_criteria": tuple(
                                decision.get("acceptance_criteria", kr.acceptance_criteria)
                            ),
                            "version": kr.version + 1,
                        }
                    )
                    if kr.kr_id == target
                    else kr
                    for kr in objective.key_results
                )
                revised.append(objective.model_copy(update={"key_results": krs}))
            validate_plan(revised)
            update["objectives"] = [o.model_dump(mode="json") for o in revised]
            ids = {target}
            changed = True
            while changed:
                before = len(ids)
                ids.update(
                    kr.kr_id for kr in _krs(state).values() if set(kr.dependency_kr_ids) & ids
                )
                changed = len(ids) != before
        if decision["action"] == "retry_operation":
            resolve = getattr(services, "resolve_operation", None)
            if resolve is not None:
                await resolve(decision)
        return {
            **reset_epochs(state, ids, decision.get("context", "Human review resolved")),
            **update,
            "route": "coordinate",
        }

    async def finish(state: ExecutiveState) -> JSON:
        outcomes = list(_current_outcomes(state).values())
        status = state.get("status", "failed")
        objectives = [StrategicObjective.model_validate(o) for o in state.get("objectives", [])]
        report = state.get("report", "")
        if status == "completed":
            try:
                report = await services.synthesize(state["user_request"], objectives, outcomes)
            except EscalationSignal as exc:
                status = "failed"
                report = f"Final report synthesis failed ({exc.kind}): {exc.reason}"
            # Deterministic ledger keeps every approval and artifact traceable even if
            # a prose synthesizer omits one of them.
            ledger = "\n".join(
                f"- {o.kr_id} v{o.version}, epoch {o.epoch}: {o.status}; artifacts: "
                + (", ".join(o.deliverable.artifact_ids) if o.deliverable else "none")
                for o in outcomes
            )
            report = f"{report}\n\nApproval evidence\n{ledger}"
        elif not report:
            report = (
                f"Run {status}. {sum(o.status == 'passed' for o in outcomes)} key results passed."
            )
        await services.emit(
            "executive", "completed" if status == "completed" else "error", f"Run {status}"
        )
        return {"report": report, "status": status}

    builder = StateGraph(ExecutiveState)
    builder.add_node("plan", plan)
    builder.add_node("coordinate", coordinate)
    builder.add_node("department", run_department)
    builder.add_node("replan", replan)
    builder.add_node("review", human_review)
    builder.add_node("finish", finish)
    builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan",
        lambda state: state.get("route", "coordinate"),
        {"coordinate": "coordinate", "review": "review", "finish": "finish"},
    )
    builder.add_conditional_edges("coordinate", route, ["department", "review", "replan", "finish"])
    builder.add_edge("department", "coordinate")
    builder.add_edge("replan", "coordinate")
    builder.add_conditional_edges(
        "review",
        lambda state: state["route"],
        {"coordinate": "coordinate", "plan": "plan", "finish": "finish"},
    )
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer, store=store)
