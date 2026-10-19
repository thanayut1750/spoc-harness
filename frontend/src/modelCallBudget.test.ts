import { describe, expect, it } from "vitest";
import { parseCallBudget, validCallBudgetValue } from "./modelCallBudget";

describe("model-call budgets", () => {
  it("accepts the unchanged defaults and both inclusive budget boundaries", () => {
    expect(parseCallBudget("100", "12")).toEqual({
      max_model_calls: 100,
      worker_model_calls: 12,
    });
    expect(parseCallBudget("1", "1")).toEqual({
      max_model_calls: 1,
      worker_model_calls: 1,
    });
    expect(parseCallBudget("10000", "100")).toEqual({
      max_model_calls: 10000,
      worker_model_calls: 100,
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
    });
    expect(validCallBudgetValue("9007199254740992", 10000)).toBe(false);
  });
  it("encodes each unlimited choice as an explicit null independently of the finite draft", () => {
    expect(parseCallBudget("", "12", { missionUnlimited: true })).toEqual({
      max_model_calls: null,
      worker_model_calls: 12,
    });
    expect(parseCallBudget("240", "", { workerUnlimited: true })).toEqual({
      max_model_calls: 240,
      worker_model_calls: null,
    });
    expect(
      parseCallBudget("", "", {
        missionUnlimited: true,
        workerUnlimited: true,
      }),
    ).toEqual({ max_model_calls: null, worker_model_calls: null });
  });
  it("still validates any finite side when the other budget is unlimited", () => {
    expect(parseCallBudget("", "101", { missionUnlimited: true })).toBeNull();
    expect(parseCallBudget("10001", "", { workerUnlimited: true })).toBeNull();
    expect(parseCallBudget("null", "12")).toBeNull();
  });
});
