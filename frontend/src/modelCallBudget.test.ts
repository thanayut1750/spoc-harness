import { describe, expect, it } from "vitest";
import {
  canApplyCallBudget,
  formatCallLimit,
  matchesSavedCallBudget,
  normalizeCallBudget,
  parseCallBudget,
  validCallBudgetValue,
} from "./modelCallBudget";

describe("call budgets", () => {
  it("accepts the unchanged defaults and both inclusive budget boundaries", () => {
    expect(parseCallBudget("100", "12")).toEqual({
      max_model_calls: 100,
      worker_model_calls: 12,
      max_tool_calls: 200,
    });
    expect(parseCallBudget("1", "1")).toEqual({
      max_model_calls: 1,
      worker_model_calls: 1,
      max_tool_calls: 200,
    });
    expect(parseCallBudget("10000", "100")).toEqual({
      max_model_calls: 10000,
      worker_model_calls: 100,
      max_tool_calls: 200,
    });
  });
  it("rejects empty, fractional, nonnumeric, negative, zero, and excessive limits", () => {
    for (const invalid of [
      "",
      " ",
      "0",
      "-1",
      "1.5",
      "NaN",
      "Infinity",
      "abc",
      "10001",
    ])
      expect(parseCallBudget(invalid, "12")).toBeNull();
    for (const invalid of ["", "0", "-1", "12.5", "101", "10000"])
      expect(parseCallBudget("100", invalid)).toBeNull();
  });
  it("keeps the per-invocation cap independent while the mission budget still bounds total requests", () => {
    expect(parseCallBudget("1", "100")).toEqual({
      max_model_calls: 1,
      worker_model_calls: 100,
      max_tool_calls: 200,
    });
    expect(validCallBudgetValue("9007199254740992", 10000)).toBe(false);
  });
  it("encodes each unlimited choice as an explicit null independently of the finite draft", () => {
    expect(parseCallBudget("", "12", { missionUnlimited: true })).toEqual({
      max_model_calls: null,
      worker_model_calls: 12,
      max_tool_calls: 200,
    });
    expect(parseCallBudget("240", "", { workerUnlimited: true })).toEqual({
      max_model_calls: 240,
      worker_model_calls: null,
      max_tool_calls: 200,
    });
    expect(
      parseCallBudget("", "", {
        missionUnlimited: true,
        workerUnlimited: true,
      }),
    ).toEqual({
      max_model_calls: null,
      worker_model_calls: null,
      max_tool_calls: 200,
    });
  });
  it("still validates any finite side when the other budget is unlimited", () => {
    expect(parseCallBudget("", "101", { missionUnlimited: true })).toBeNull();
    expect(parseCallBudget("10001", "", { workerUnlimited: true })).toBeNull();
    expect(parseCallBudget("null", "12")).toBeNull();
  });
  it("keeps the tool cap finite when both model caps are removed", () => {
    expect(
      parseCallBudget("", "", {
        missionUnlimited: true,
        workerUnlimited: true,
        toolCalls: "340",
      }),
    ).toEqual({
      max_model_calls: null,
      worker_model_calls: null,
      max_tool_calls: 340,
    });
    expect(
      parseCallBudget("100", "12", {
        toolCalls: "",
        toolUnlimited: true,
      }),
    ).toEqual({
      max_model_calls: 100,
      worker_model_calls: 12,
      max_tool_calls: null,
    });
    expect(
      parseCallBudget("", "", {
        missionUnlimited: true,
        workerUnlimited: true,
        toolUnlimited: true,
        toolCalls: "",
      }),
    ).toEqual({
      max_model_calls: null,
      worker_model_calls: null,
      max_tool_calls: null,
    });
  });
  it("validates the tool-call boundaries even when model budgets are unlimited", () => {
    for (const value of ["1", "100000"])
      expect(
        parseCallBudget("100", "12", { toolCalls: value })?.max_tool_calls,
      ).toBe(Number(value));
    for (const value of ["", "0", "-1", "1.5", "100001", "null"])
      expect(
        parseCallBudget("", "", {
          missionUnlimited: true,
          workerUnlimited: true,
          toolCalls: value,
        }),
      ).toBeNull();
  });
  it("resolves only a missing legacy tool cap to 200, preserving explicit nulls", () => {
    expect(
      normalizeCallBudget({ max_model_calls: null, worker_model_calls: null }),
    ).toEqual({
      max_model_calls: null,
      worker_model_calls: null,
      max_tool_calls: 200,
    });
    expect(
      normalizeCallBudget({
        max_model_calls: null,
        worker_model_calls: 12,
        max_tool_calls: null,
      }).max_tool_calls,
    ).toBeNull();
    expect(formatCallLimit(undefined)).toBe("Not reported");
    expect(formatCallLimit(null)).toBe("No limit");
    expect(formatCallLimit(200)).toBe("200");
  });
  it("offers explicit mission-budget updates only in safe stopped states", () => {
    for (const status of ["paused", "review", "failed"])
      expect(
        canApplyCallBudget({ run_id: "run", user_request: "task", status }),
      ).toBe(true);
    for (const status of [
      "queued",
      "running",
      "succeeded",
      "cancelled",
      "unknown",
    ])
      expect(
        canApplyCallBudget({ run_id: "run", user_request: "task", status }),
      ).toBe(false);
    expect(canApplyCallBudget(null)).toBe(false);
    expect(
      canApplyCallBudget({
        run_id: "run",
        user_request: "task",
        status: "review",
        cancel_requested: true,
      }),
    ).toBe(false);
  });
  it("requires saving changed budgets before applying them, including removing only the tool cap", () => {
    const saved = { max_model_calls: null, worker_model_calls: null };
    expect(
      matchesSavedCallBudget({ ...saved, max_tool_calls: 200 }, saved),
    ).toBe(true);
    expect(
      matchesSavedCallBudget({ ...saved, max_tool_calls: null }, saved),
    ).toBe(false);
    expect(
      matchesSavedCallBudget({ ...saved, max_tool_calls: 201 }, saved),
    ).toBe(false);
    expect(matchesSavedCallBudget(null, saved)).toBe(false);
    expect(
      matchesSavedCallBudget(
        { ...saved, max_tool_calls: null },
        { ...saved, max_tool_calls: null },
      ),
    ).toBe(true);
  });
});
