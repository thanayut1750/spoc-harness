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
  provide_context: "Provide context and retry",
  revise_kr: "Revise a key result",
  retry_operation: "Retry the reviewed operation",
  continue: "Continue execution",
  abort: "Abort this run",
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
