import type { ModelCallBudget } from "./types";

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
  }: {
    missionUnlimited?: boolean;
    workerUnlimited?: boolean;
  } = {},
): ModelCallBudget | null {
  if (
    (!missionUnlimited && !validCallBudgetValue(mission, 10000)) ||
    (!workerUnlimited && !validCallBudgetValue(worker, 100))
  )
    return null;
  return {
    max_model_calls: missionUnlimited ? null : Number(mission),
    worker_model_calls: workerUnlimited ? null : Number(worker),
  };
}
