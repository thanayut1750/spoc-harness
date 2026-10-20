import type { ModelCallBudget, Run } from "./types";

export function autonomousCallBudget(budget?: Partial<ModelCallBudget> | null) {
  return (
    !!budget &&
    budget.max_model_calls === null &&
    budget.worker_model_calls === null &&
    budget.max_tool_calls === null
  );
}

export function normalizeCallBudget(
  budget: ModelCallBudget,
): Required<ModelCallBudget> {
  return {
    max_model_calls: budget.max_model_calls,
    worker_model_calls: budget.worker_model_calls,
    max_tool_calls:
      budget.max_tool_calls === undefined ? 200 : budget.max_tool_calls,
  };
}

export function canApplyCallBudget(run?: Run | null) {
  return (
    !!run &&
    !run.cancel_requested &&
    ["paused", "review", "failed"].includes(run.status)
  );
}

export function matchesSavedCallBudget(
  draft: ModelCallBudget | null,
  saved: ModelCallBudget,
) {
  if (!draft) return false;
  const proposed = normalizeCallBudget(draft);
  const current = normalizeCallBudget(saved);
  return (
    proposed.max_model_calls === current.max_model_calls &&
    proposed.worker_model_calls === current.worker_model_calls &&
    proposed.max_tool_calls === current.max_tool_calls
  );
}

export function formatCallLimit(value: number | null | undefined) {
  return value === null
    ? "No limit"
    : value === undefined
      ? "Not reported"
      : String(value);
}

export function validCallBudgetValue(value: string, maximum: number) {
  if (!/^\d+$/.test(value.trim())) return false;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 1 && number <= maximum;
}

export function parseCallBudget(
  mission: string,
  worker: string,
  {
    missionUnlimited = false,
    workerUnlimited = false,
    toolCalls = "200",
    toolUnlimited = false,
  }: {
    missionUnlimited?: boolean;
    workerUnlimited?: boolean;
    toolCalls?: string;
    toolUnlimited?: boolean;
  } = {},
): ModelCallBudget | null {
  if (
    (!missionUnlimited && !validCallBudgetValue(mission, 10000)) ||
    (!workerUnlimited && !validCallBudgetValue(worker, 100)) ||
    (!toolUnlimited && !validCallBudgetValue(toolCalls, 100000))
  )
    return null;
  return {
    max_model_calls: missionUnlimited ? null : Number(mission),
    worker_model_calls: workerUnlimited ? null : Number(worker),
    max_tool_calls: toolUnlimited ? null : Number(toolCalls),
  };
}
