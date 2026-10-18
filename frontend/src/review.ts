import { progressStatus } from "./office";
import type {
  ActivityEvent,
  Artifact,
  Evaluation,
  ReviewAction,
  ReviewAttempt,
  ReviewKeyResult,
  Run,
} from "./types";
export const actionLabels: Record<ReviewAction, string> = {
  provide_context: "Retry task",
  revise_kr: "Change requirements",
  retry_operation: "Run command again",
  continue: "Resume work",
  abort: "Stop run",
};
export const actionImplications: Record<ReviewAction, string> = {
  provide_context:
    "Adds your guidance and starts another execution epoch for the blocked work. The team must produce new evidence against the current acceptance criteria.",
  revise_kr:
    "Creates a new version of the selected key result and invalidates approvals that depend on it. The organization then schedules the affected work again.",
  retry_operation:
    "Executes the reviewed host operation again. Its earlier outcome is unknown, so inspect the command and available logs before retrying.",
  continue: "Resumes the saved workflow from this pause boundary.",
  abort:
    "Ends this run. Existing files and evidence remain available for inspection.",
};
export function reviewReason(run: Run): string {
  return (
    run.review?.reason ||
    run.review?.message ||
    "The workflow is waiting for a human decision."
  );
}
export function allowedActions(run: Run): ReviewAction[] {
  const actions = run.review?.allowed_actions;
  if (actions)
    return actions.filter((action) => Object.hasOwn(actionLabels, action));
  if (run.review?.kind === "manual_pause") return ["continue", "abort"];
  if (run.review?.kind === "unknown_operation")
    return ["retry_operation", "abort"];
  return ["provide_context", "revise_kr", "abort"];
}
function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}
function text(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}
function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}
function fallbackAttempts(
  run: Run,
  id: string,
  events: ActivityEvent[],
): ReviewAttempt[] {
  return events
    .filter(
      (event) =>
        event.run_id === run.run_id &&
        event.kr_id === id &&
        (event.data?.evaluation || event.data?.deliverable),
    )
    .sort((a, b) => a.seq - b.seq)
    .map((event) => {
      const deliverable = record(event.data?.deliverable);
      const evaluation = record(event.data?.evaluation) as
        Evaluation | undefined;
      return {
        attempt_id: event.event_id,
        stage: event.agent_id.includes("gatekeeper") ? "worker" : "department",
        role: event.agent_id,
        summary: text(deliverable?.summary),
        artifact_ids: strings(deliverable?.artifact_ids),
        evidence: strings(deliverable?.evidence),
        evaluation,
        reason: evaluation?.feedback,
        timestamp: event.timestamp,
      };
    });
}
export function reviewFocus(
  run: Run,
  events: ActivityEvent[] = [],
): { blocked: ReviewKeyResult[]; waiting: ReviewKeyResult[] } {
  const definitions =
    run.objectives?.flatMap((objective) => objective.key_results) ?? [];
  const context = run.review?.context;
  const packet = context?.key_results ?? [];
  const escalated = Object.entries(run.outcomes ?? {})
    .filter(([, outcome]) => !!outcome.escalation)
    .map(([id]) => id);
  const blockers =
    context?.blockers
      ?.map((blocker) => blocker.kr_id)
      .filter((id): id is string => !!id) ?? [];
  const focused = blockers.length
    ? blockers
    : escalated.length
      ? escalated
      : definitions
          .filter((kr) =>
            ["failed", "blocked", "escalated"].includes(
              progressStatus(run.progress?.[kr.kr_id]),
            ),
          )
          .map((kr) => kr.kr_id);
  const requested =
    run.review?.kr_ids ?? (run.review?.kr_id ? [run.review.kr_id] : []);
  const ids = focused.length ? focused : requested;
  const resultFor = (id: string): ReviewKeyResult => {
    const definition = definitions.find((kr) => kr.kr_id === id);
    const supplied = packet.find((kr) => kr.kr_id === id);
    const outcome = run.outcomes?.[id];
    const deliverable = record(outcome?.deliverable);
    const escalation = record(outcome?.escalation);
    return {
      kr_id: id,
      version: definition?.version ?? 1,
      epoch: run.epochs?.[id],
      department: definition?.target_department,
      description: definition?.description ?? id,
      acceptance_criteria: definition?.acceptance_criteria ?? [],
      status: progressStatus(run.progress?.[id]),
      reason: text(escalation?.reason),
      evaluation: outcome?.evaluation ?? undefined,
      summary: text(deliverable?.summary),
      artifact_ids: strings(deliverable?.artifact_ids),
      evidence: strings(deliverable?.evidence),
      attempts: fallbackAttempts(run, id, events),
      ...supplied,
    };
  };
  const blocked = ids.map(resultFor);
  const waiting = definitions
    .filter(
      (kr) =>
        !ids.includes(kr.kr_id) &&
        progressStatus(run.progress?.[kr.kr_id]) === "pending",
    )
    .map((kr) => resultFor(kr.kr_id));
  return { blocked, waiting };
}
export type ArtifactGroup =
  | "Task outputs"
  | "Sources"
  | "Verification logs"
  | "Submission metadata"
  | "Other files";
export const artifactGroups: ArtifactGroup[] = [
  "Task outputs",
  "Sources",
  "Verification logs",
  "Submission metadata",
  "Other files",
];
export function artifactGroup(artifact: Artifact): ArtifactGroup {
  if (
    ["source", "task_output", "output", "report"].includes(artifact.kind ?? "")
  )
    return "Task outputs";
  if (["research", "web_source", "retrieval"].includes(artifact.kind ?? ""))
    return "Sources";
  if (
    [
      "command_log",
      "command_result",
      "verification",
      "verification_log",
      "log",
    ].includes(artifact.kind ?? "")
  )
    return "Verification logs";
  if (["deliverable", "manifest", "metadata"].includes(artifact.kind ?? ""))
    return "Submission metadata";
  return "Other files";
}
export function artifactSizeLabel(artifact: Artifact): string {
  if (artifact.size === 0)
    return artifactGroup(artifact) === "Verification logs"
      ? "Empty log · no diagnostic output"
      : artifactGroup(artifact) === "Task outputs"
        ? "Empty task output"
        : "Empty file";
  return typeof artifact.size === "number"
    ? `${(artifact.size / 1024).toFixed(1)} KB`
    : "Size not recorded";
}

export const retryDirective =
  "Try the blocked work again using the current requirements and recorded feedback.";
export const actionCtas: Record<ReviewAction, string> = {
  provide_context: "Retry task",
  revise_kr: "Save changes and retry",
  retry_operation: "Run command again",
  continue: "Resume work",
  abort: "Stop run",
};
export function recommendedAction(run: Run): ReviewAction {
  const actions = allowedActions(run);
  const preferred =
    run.review?.kind === "manual_pause"
      ? "continue"
      : run.review?.kind === "unknown_operation"
        ? "retry_operation"
        : "provide_context";
  return actions.includes(preferred)
    ? preferred
    : (actions.find((action) => action !== "abort") ?? "abort");
}
export function reviewPresentation(run: Run): {
  summary: string;
  warning?: string;
  requiresGuidance: boolean;
  sourceUnavailable: boolean;
  unknownOperation: boolean;
  policyIssue: boolean;
  usageLimit?: boolean;
  workerTimeout?: boolean;
} {
  const kind = run.review?.kind ?? "";
  const reason = reviewReason(run);
  const classifications =
    run.review?.context?.blockers?.map((blocker) => blocker.classification) ??
    [];
  const policyIssue =
    classifications.includes("policy_violation") ||
    (kind === "constitution_violation" &&
      !classifications.includes("quality_or_execution_failure"));
  const unknownOperation = kind === "unknown_operation";
  const sourceUnavailable =
    kind === "missing_resource" ||
    /reader.*fail|source.*(?:unavailable|could not|failed)|entitlement|quota|MCPError/i.test(
      reason,
    );
  const clarification =
    [
      "clarification",
      "clarification_required",
      "human_clarification",
      "ambiguity",
      "ambiguous_request",
      "missing_information",
    ].includes(kind) ||
    (!sourceUnavailable &&
      /clarif(?:y|ication)|ambiguous|unclear (?:requirement|request)|missing (?:information|requirements)/i.test(
        reason,
      ));
  if (kind === "manual_pause")
    return {
      summary: "The team is paused. Resume when you’re ready.",
      requiresGuidance: false,
      sourceUnavailable: false,
      unknownOperation: false,
      policyIssue: false,
    };
  if (unknownOperation)
    return {
      summary: "A command ended before its outcome was recorded.",
      warning:
        "The command may already have changed files. Running it again can repeat those changes. Check the recorded evidence before retrying.",
      requiresGuidance: false,
      sourceUnavailable: false,
      unknownOperation: true,
      policyIssue: false,
    };
  if (policyIssue)
    return {
      summary: "The team stopped because a rule may have been violated.",
      warning: reason.length > 260 ? `${reason.slice(0, 257)}…` : reason,
      requiresGuidance: true,
      sourceUnavailable: false,
      unknownOperation: false,
      policyIssue: true,
    };
  if (clarification)
    return {
      summary: "The team needs a detail from you before it can continue.",
      warning: reason.length > 240 ? `${reason.slice(0, 237)}…` : reason,
      requiresGuidance: true,
      sourceUnavailable: false,
      unknownOperation: false,
      policyIssue: false,
    };
  if (
    kind === "limit_exceeded" ||
    /usage limit|model.call limit|tool.call limit|budget.{0,30}(?:exceeded|exhausted)|allowance/i.test(
      reason,
    )
  )
    return {
      summary: "The team reached an execution limit.",
      usageLimit: true,
      warning:
        "Retrying does not reset this run’s usage allowance. Review the limit or stop the run before spending more calls.",
      requiresGuidance: false,
      sourceUnavailable: false,
      unknownOperation: false,
      policyIssue: false,
    };
  if (
    kind === "worker_timeout" ||
    run.review?.source_kind === "worker_timeout" ||
    run.review?.context?.blockers?.some(
      (blocker) => blocker.kind === "worker_timeout",
    ) ||
    /\bwork limit\b|\bworker.{0,30}timed out\b/i.test(reason)
  )
    return {
      summary: "The worker reached its time limit before finishing.",
      workerTimeout: true,
      warning: `${reason.length > 240 ? `${reason.slice(0, 237)}…` : reason} Retry can reuse saved sources; the per-worker limit and run allowance stay unchanged.`,
      requiresGuidance: false,
      sourceUnavailable: false,
      unknownOperation: false,
      policyIssue: false,
    };
  if (sourceUnavailable)
    return {
      summary:
        "A required source could not be read. Retry after access is restored, or add an alternative source.",
      requiresGuidance: false,
      sourceUnavailable: true,
      unknownOperation: false,
      policyIssue: false,
    };
  if (
    /empty result|empty deliverable|no (?:usable )?(?:task )?output|no deliverable|did not produce/i.test(
      reason,
    )
  )
    return {
      summary:
        "The task returned no usable output. You can retry it or change its requirements.",
      requiresGuidance: false,
      sourceUnavailable: false,
      unknownOperation: false,
      policyIssue: false,
    };
  return {
    summary:
      "The task could not meet its requirements. Choose how the team should continue.",
    requiresGuidance: false,
    sourceUnavailable: false,
    unknownOperation: false,
    policyIssue: false,
  };
}
export function retryContext(run: Run, note: string): string {
  const focus = reviewFocus(run);
  const feedback = [
    reviewReason(run),
    ...focus.blocked
      .map((kr) => kr.evaluation?.feedback)
      .filter((value): value is string => !!value),
  ];
  const unique = [...new Set(feedback)];
  return [
    retryDirective,
    `Recorded review feedback:\n${unique.join("\n\n")}`,
    ...(note.trim() ? [`Additional instructions:\n${note.trim()}`] : []),
  ].join("\n\n");
}
export function reviewOperation(run: Run): { command?: string; cwd?: string } {
  const operation =
    record(record(run.review?.context)?.operation) ??
    record(run.review?.operation);
  const request = record(operation?.request);
  return {
    command:
      text(operation?.command) ??
      text(request?.command) ??
      text(run.review?.command),
    cwd: text(operation?.cwd) ?? text(request?.cwd),
  };
}
