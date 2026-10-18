import { describe, expect, it } from "vitest";
import {
  allowedActions,
  artifactGroup,
  artifactSizeLabel,
  reviewFocus,
  reviewReason,
  retryContext,
  retryDirective,
  reviewPresentation,
  reviewOperation,
} from "./review";
import type { Artifact, Run } from "./types";
const run: Run = {
  run_id: "run",
  status: "review",
  user_request: "Build a visualization",
  objectives: [
    {
      objective_id: "O1",
      title: "Build",
      key_results: [
        {
          kr_id: "KR1",
          description: "Create a cited inventory",
          target_department: "research",
          acceptance_criteria: ["Write a JSON file", "Cite each entity"],
          dependency_kr_ids: [],
          version: 1,
        },
        {
          kr_id: "KR2",
          description: "Build the scene",
          target_department: "engineering",
          acceptance_criteria: ["Scene renders"],
          dependency_kr_ids: ["KR1"],
          version: 1,
        },
      ],
    },
  ],
  progress: { KR1: "escalated", KR2: "pending" },
  epochs: { KR1: 3 },
  outcomes: {
    KR1: {
      escalation: {
        kind: "empty_result",
        reason: "The worker produced no inventory.",
      },
    },
  },
  review: {
    interrupt_id: "actual",
    kind: "constitution_violation",
    reason: "The worker produced no inventory.",
    kr_ids: ["KR1", "KR2"],
    allowed_actions: ["provide_context", "revise_kr", "abort"],
  },
};
describe("review context", () => {
  it("shows the recorded backend reason and preserves only allowed decisions", () => {
    expect(reviewReason(run)).toBe("The worker produced no inventory.");
    expect(allowedActions(run)).toEqual([
      "provide_context",
      "revise_kr",
      "abort",
    ]);
  });
  it("focuses actual failures and distinguishes pending dependencies in legacy reviews", () => {
    const focus = reviewFocus(run);
    expect(focus.blocked.map((result) => result.kr_id)).toEqual(["KR1"]);
    expect(focus.blocked[0].acceptance_criteria).toEqual([
      "Write a JSON file",
      "Cite each entity",
    ]);
    expect(focus.blocked[0].epoch).toBe(3);
    expect(focus.waiting.map((result) => result.kr_id)).toEqual(["KR2"]);
  });
  it("uses the persisted attempt history and packet blocker IDs after refresh", () => {
    const enriched: Run = {
      ...run,
      review: {
        ...run.review!,
        context: {
          mission: run.user_request,
          blockers: [{ kr_id: "KR1", reason: "No inventory" }],
          key_results: [
            {
              kr_id: "KR1",
              description: "Create a cited inventory",
              acceptance_criteria: ["Write JSON"],
              attempts: [
                {
                  attempt_id: "attempt-1",
                  summary: "No output returned",
                  artifact_ids: [],
                  evidence: [],
                  evaluation: { score: 0, feedback: "No file exists" },
                  approved: false,
                },
              ],
            },
          ],
        },
      },
    };
    expect(
      reviewFocus(enriched).blocked[0].attempts?.[0].evaluation?.feedback,
    ).toBe("No file exists");
  });
});
describe("artifact meaning", () => {
  const file = (kind: string, size: number): Artifact => ({
    artifact_id: kind,
    name: `${kind}.json`,
    media_type: "application/json",
    kind,
    size,
  });
  it("does not count raw sources, submission metadata, or logs as task outputs", () => {
    expect(artifactGroup(file("research", 86000))).toBe("Sources");
    expect(artifactGroup(file("deliverable", 270))).toBe("Submission metadata");
    expect(artifactGroup(file("command_log", 0))).toBe("Verification logs");
    expect(artifactGroup(file("task_output", 1200))).toBe("Task outputs");
    expect(artifactGroup(file("source", 1200))).toBe("Task outputs");
  });
  it("distinguishes a normal empty diagnostic log from an empty generated file", () => {
    expect(artifactSizeLabel(file("command_log", 0))).toBe(
      "Empty log · no diagnostic output",
    );
    expect(artifactSizeLabel(file("task_output", 0))).toBe("Empty task output");
  });
});

describe("compact decision semantics", () => {
  it("preserves actual recorded feedback when retrying and labels added instructions separately", () => {
    const ordinary: Run = {
      ...run,
      review: {
        ...run.review!,
        kind: "missing_resource",
        reason: "Reader access failed.",
        context: {
          key_results: [
            {
              kr_id: "KR1",
              description: "Research",
              acceptance_criteria: ["Cite sources"],
              evaluation: { feedback: "No citation was recovered." },
            },
          ],
        },
      },
    };
    const context = retryContext(ordinary, "Use a supplied source URL.");
    expect(context).toContain(retryDirective);
    expect(context).toContain(
      "Recorded review feedback:\nReader access failed.",
    );
    expect(context).toContain("No citation was recovered.");
    expect(context).toContain(
      "Additional instructions:\nUse a supplied source URL.",
    );
  });
  it("distinguishes source failures from policy and human clarification decisions", () => {
    expect(
      reviewPresentation({
        ...run,
        review: { ...run.review!, kind: "missing_resource" },
      }),
    ).toMatchObject({ sourceUnavailable: true, requiresGuidance: false });
    expect(reviewPresentation(run)).toMatchObject({
      policyIssue: true,
      requiresGuidance: true,
    });
    expect(
      reviewPresentation({
        ...run,
        review: {
          ...run.review!,
          kind: "clarification",
          reason: "Which dataset should be used?",
        },
      }),
    ).toMatchObject({ requiresGuidance: true, policyIssue: false });
  });
  it("keeps unknown command and usage-limit risks explicit without claiming a reset", () => {
    expect(
      reviewPresentation({
        ...run,
        review: { ...run.review!, kind: "unknown_operation" },
      }).warning,
    ).toContain("may already have changed files");
    expect(
      reviewPresentation({
        ...run,
        review: { ...run.review!, kind: "limit_exceeded" },
      }).warning,
    ).toContain("does not reset");
    expect(
      reviewOperation({
        ...run,
        review: {
          ...run.review!,
          operation: { command: "python validate.py", cwd: "/tmp/work" },
        },
      }),
    ).toEqual({ command: "python validate.py", cwd: "/tmp/work" });
  });
});
