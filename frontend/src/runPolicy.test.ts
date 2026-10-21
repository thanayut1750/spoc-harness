import { describe, expect, it } from "vitest";
import { autonomousCallBudget } from "./modelCallBudget";
import { autonomousContinuation, requiresHumanReview } from "./runPolicy";
import type { Run } from "./types";
const unlimited = {
  max_model_calls: null,
  worker_model_calls: null,
  max_tool_calls: null,
};
const run: Run = {
  run_id: "run",
  user_request: "Finish the evidence inventory",
  status: "queued",
  limits: unlimited,
  continuation: {
    attempt: 4,
    reason: "Source rate limit; retrying saved progress",
    scheduled_at: "2026-10-20T10:00:00Z",
  },
  next_attempt_at: "2026-10-20T10:05:00Z",
  automatic_cycles: 3,
  autonomous_failures: 2,
};
describe("autonomous mission presentation", () => {
  it("requires three explicit unlimited caps and keeps legacy or finite missions governed", () => {
    expect(autonomousCallBudget(unlimited)).toBe(true);
    expect(
      autonomousCallBudget({ max_model_calls: null, worker_model_calls: null }),
    ).toBe(false);
    expect(autonomousCallBudget({ ...unlimited, max_tool_calls: 200 })).toBe(
      false,
    );
    expect(autonomousCallBudget(undefined)).toBe(false);
  });
  it("shows queued machine continuation with its actual wakeup and recorded progress", () => {
    expect(autonomousContinuation(run)).toEqual({
      title: "Automatic continuation scheduled",
      reason: run.continuation!.reason,
      wakeAt: run.next_attempt_at,
      cycles: 3,
      failures: 2,
      attempt: 4,
    });
    expect(requiresHumanReview(run)).toBe(false);
  });
  it("shows automatic recovery for an older routine review without an approval requirement", () => {
    const review = {
      ...run,
      status: "review",
      review: {
        interrupt_id: "old",
        kind: "blocked",
        reason: "Needs another source",
      },
    };
    expect(requiresHumanReview(review)).toBe(false);
    expect(autonomousContinuation(review)?.title).toBe(
      "Autonomous recovery pending",
    );
  });
  it("does not show a stale waiting reason or wakeup while work is running", () => {
    const state = autonomousContinuation({ ...run, status: "running" });
    expect(state?.title).toBe("Autonomous mode");
    expect(state?.reason).not.toContain("rate limit");
    expect(state?.wakeAt).toBeNull();
  });
  it("reads the persisted automatic_cycles field even without queued continuation metadata", () => {
    expect(
      autonomousContinuation({
        ...run,
        status: "running",
        automatic_cycles: 7,
        continuation: null,
      })?.cycles,
    ).toBe(7);
  });
  it("preserves manual pause review and hides automatic continuation for cancellation or terminal states", () => {
    const paused = {
      ...run,
      status: "paused",
      review: { interrupt_id: "pause", kind: "manual_pause" },
    };
    expect(requiresHumanReview(paused)).toBe(true);
    expect(autonomousContinuation(paused)).toBeNull();
    expect(
      autonomousContinuation({ ...run, pause_requested: true }),
    ).toBeNull();
    expect(
      autonomousContinuation({ ...run, cancel_requested: true }),
    ).toBeNull();
    for (const status of ["failed", "succeeded", "cancelled"])
      expect(autonomousContinuation({ ...run, status })).toBeNull();
  });
  it("retains ordinary review controls whenever any mission cap is finite", () => {
    const finite = {
      ...run,
      status: "review",
      limits: { ...unlimited, max_tool_calls: 200 },
      review: { interrupt_id: "gate", kind: "blocked" },
    };
    expect(requiresHumanReview(finite)).toBe(true);
    expect(autonomousContinuation(finite)).toBeNull();
  });
});
