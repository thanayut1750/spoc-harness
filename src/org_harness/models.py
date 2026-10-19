"""Immutable boundary contracts for graph execution, tools, and HTTP clients."""

import hashlib
import json
import re
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from org_harness.text_safety import require_json_text

Department = Literal["research", "engineering"]
ExecutionMode = Literal["FAST_TRACK", "DEPARTMENTAL", "FULL_PYRAMID"]
Activity = Literal[
    "idle",
    "planning",
    "reading",
    "writing",
    "executing",
    "reviewing",
    "waiting",
    "completed",
    "error",
]
Role = Literal["market_researcher", "data_analyst", "system_architect", "backend_coder"]
ConfigurableAgent = Literal[
    "planner",
    "executive",
    "research_head",
    "engineering_head",
    "research_gatekeeper",
    "engineering_gatekeeper",
    "market_researcher",
    "data_analyst",
    "system_architect",
    "backend_coder",
    "tools_rd_lead",
]

EngineeringToolName = Literal[
    "read_file",
    "write_file",
    "publish_file",
    "read_artifact",
    "read_web_page",
    "run_command",
    "validate_code_syntax",
    "run_mission_tool",
]
ENGINEERING_TOOL_NAMES = frozenset(get_args(EngineeringToolName))
# Task-specific selections narrow optional capabilities. Every specialist still
# needs the artifact protocol to read evidence, save outputs, and report blockers.
ENGINEERING_CORE_TOOL_NAMES = frozenset({"write_file", "read_artifact", "escalate_blocker"})


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def persistable_text(cls, value: Any) -> Any:
        return require_json_text(value)


class Constitution(Contract):
    mission_statement: str = Field(
        default="Complete the objective with traceable evidence.", min_length=1
    )
    prohibited_actions: tuple[str, ...] = ()
    compliance_rules: tuple[str, ...] = ()
    max_revision_loops: int = Field(default=2, ge=0, le=10)


MaxModelCalls = Annotated[int, Field(ge=1, le=10000)] | None
WorkerModelCalls = Annotated[int, Field(ge=1, le=100)] | None


class ModelCallBudget(Contract):
    max_model_calls: MaxModelCalls = 100
    worker_model_calls: WorkerModelCalls = 12


class ModelCallBudgetUpdate(Contract):
    max_model_calls: MaxModelCalls
    worker_model_calls: WorkerModelCalls


class RunLimits(ModelCallBudget):
    max_tool_calls: int = Field(default=200, ge=1, le=100000)
    command_timeout: int = Field(default=300, ge=1, le=86400)
    worker_timeout: float = Field(default=3600, ge=0.01, le=3600)


class ModelSelection(Contract):
    provider: Literal["configured", "zai", "openai", "openai_compatible"] = "configured"
    model: str = Field(min_length=1, max_length=200, pattern=r"^[^\s\x00-\x1f]+$")
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] = "medium"


class TriageDecision(Contract):
    mode: ExecutionMode
    departments: tuple[Department, ...] = Field(min_length=1, max_length=2)
    worker_role: Role
    confidence: float = Field(ge=0, le=1)
    source: Literal["jev", "fallback", "legacy"]
    reason: str
    max_revisions: int = Field(ge=0, le=10)


class KeyResult(Contract):
    kr_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    target_department: Department
    dependency_kr_ids: tuple[str, ...] = ()
    version: int = Field(default=1, ge=1)


class StrategicObjective(Contract):
    objective_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    key_results: tuple[KeyResult, ...] = Field(min_length=1)


class StrategicPlan(Contract):
    objectives: tuple[StrategicObjective, ...] = Field(min_length=1, max_length=3)


class EngineeringSpecialistSpec(Contract):
    """Task instructions and optional capabilities; core artifact tools always remain available."""

    name: str = Field(min_length=1, max_length=80)
    instructions: str = Field(min_length=1, max_length=12000)
    tools: tuple[EngineeringToolName, ...] = ()

    @model_validator(mode="after")
    def valid_specialist(self) -> "EngineeringSpecialistSpec":
        if not self.name.strip() or not self.instructions.strip():
            raise ValueError("Specialist name and instructions must not be blank")
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("Specialist tool names must be unique")
        return self


class WorkPackage(Contract):
    work_package_id: str = Field(min_length=1)
    kr_id: str = Field(min_length=1)
    role: Role
    task: str = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    execution_attempt: int = Field(default=0, ge=0)
    critical: bool = True
    specialist: EngineeringSpecialistSpec | None = None


def worker_agent_id(run_id: str, work: WorkPackage) -> str:
    """Derive a stable identity; model output cannot impersonate another agent."""
    if work.specialist is None:
        return work.role
    scope = (
        run_id
        if re.fullmatch(r"[a-zA-Z0-9-]{1,40}", run_id)
        else hashlib.sha256(run_id.encode()).hexdigest()[:32]
    )
    definition = [run_id, work.kr_id, work.work_package_id, work.role, work.specialist.model_dump()]
    digest = hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()[:16]
    return f"specialist:{scope}:{digest}"


def worker_agent_name(work: WorkPackage) -> str:
    return work.specialist.name if work.specialist else work.role.replace("_", " ").title()


class TacticalPlan(Contract):
    work_packages: tuple[WorkPackage, ...] = Field(min_length=1, max_length=4)


class ArtifactRef(Contract):
    artifact_id: str
    name: str
    media_type: str = "text/plain"
    size: int = Field(default=0, ge=0)


class Deliverable(Contract):
    kr_id: str
    department: Department
    worker_role: str
    summary: str = Field(min_length=1)
    artifact_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    confidence_score: float = Field(default=0.5, ge=0, le=1)
    fallback: bool = False


class Evaluation(Contract):
    passed_constitution: bool
    passed_kr_criteria: bool
    score: float = Field(ge=0, le=1)
    feedback: str
    criterion_results: dict[str, bool] = Field(default_factory=dict)
    recommended_action: Literal["approve", "retry_worker", "escalate_to_exec"]
    deterministic_checks_passed: bool = True
    constitution_violations: tuple[str, ...] = ()


class Escalation(Contract):
    escalation_id: str
    kr_id: str
    kind: str
    reason: str
    resolved: bool = False


class AttemptRecord(Contract):
    """Public execution evidence retained for review without private transcripts."""

    attempt_id: str
    kr_id: str
    version: int = Field(default=1, ge=1)
    epoch: int = Field(default=0, ge=0)
    execution_attempt: int = Field(default=0, ge=0)
    stage: Literal["worker", "department"]
    work_package_id: str | None = None
    role: str
    task: str = Field(default="", max_length=2000)
    acceptance_criteria: tuple[str, ...] = ()
    summary: str = Field(default="", max_length=2000)
    artifact_ids: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    evaluation: Evaluation | None = None
    reason: str = Field(default="", max_length=2000)
    approved: bool = False


class DepartmentOutcome(Contract):
    kr_id: str
    version: int = Field(default=1, ge=1)
    epoch: int = Field(default=0, ge=0)
    status: Literal["passed", "escalated", "failed"]
    deliverable: Deliverable | None = None
    evaluation: Evaluation | None = None
    escalation: Escalation | None = None
    attempts: tuple[AttemptRecord, ...] = ()


class RunCreate(Contract):
    user_request: str = Field(min_length=1, max_length=50000)
    workspace_path: str | None = None
    constitution: Constitution = Field(default_factory=Constitution)
    limits: RunLimits = Field(default_factory=RunLimits)
    model_config_selection: ModelSelection | None = Field(default=None, alias="model_config")
    agent_model_configs: dict[ConfigurableAgent, ModelSelection] | None = None


class ReviewDecision(Contract):
    interrupt_id: str
    action: Literal["provide_context", "revise_kr", "retry_operation", "abort", "continue"]
    context: str | None = None
    kr_id: str | None = None
    description: str | None = None
    acceptance_criteria: tuple[str, ...] | None = None


class ActivityEvent(Contract):
    schema_version: Literal[1] = 1
    event_id: str = Field(min_length=1, max_length=200)
    source: str = Field(default="external", min_length=1, max_length=100)
    agent_id: str = Field(min_length=1, max_length=100)
    run_id: str | None = None
    kr_id: str | None = None
    activity: Activity
    summary: str = Field(default="", max_length=2000)
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None

    @model_validator(mode="after")
    def bounded_payload(self) -> "ActivityEvent":
        import json

        if len(json.dumps(self.data)) > 65536:
            raise ValueError("Event display payload exceeds 64 KiB")
        return self


class EscalationSignal(Exception):
    """Expected execution blocker, distinct from programming failures."""

    def __init__(self, kind: str, reason: str):
        self.kind = kind
        self.reason = reason
        super().__init__(reason)
