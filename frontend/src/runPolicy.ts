import { autonomousCallBudget } from "./modelCallBudget";
import { terminalStatuses } from "./office";
import type { Run } from "./types";

function manualPause(run: Run) {
  return (
    run.status === "paused" ||
    run.pause_requested ||
    run.review?.kind === "manual_pause"
  );
}
export function requiresHumanReview(run: Run | null) {
  return (
    !!run?.review && (!autonomousCallBudget(run.limits) || manualPause(run))
  );
}
export function autonomousContinuation(run: Run | null) {
  if (
    !run ||
    !autonomousCallBudget(run.limits) ||
    run.cancel_requested ||
    manualPause(run) ||
    terminalStatuses.has(run.status)
  )
    return null;
  const running = run.status === "running";
  const pendingReview = run.status === "review";
  return {
    title: running
      ? "Autonomous mode"
      : pendingReview
        ? "Autonomous recovery pending"
        : run.continuation
          ? "Automatic continuation scheduled"
          : "Autonomous mission queued",
    reason: running
      ? "Working in bounded cycles with saved progress."
      : run.continuation?.reason ||
        run.review?.reason ||
        "The worker will continue from saved progress automatically.",
    wakeAt: !running && !pendingReview ? run.next_attempt_at : null,
    cycles: run.automatic_cycles ?? 0,
    failures: run.autonomous_failures ?? 0,
    attempt: run.continuation?.attempt ?? 0,
  };
}
