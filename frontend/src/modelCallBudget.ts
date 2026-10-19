import type { ModelCallBudget } from "./types";

export function validCallBudgetValue(value: string, maximum: number) {
  if (!/^\d+$/.test(value.trim())) return false;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 1 && number <= maximum;
}

export function parseCallBudget(
  mission: string,
  worker: string,
): ModelCallBudget | null {
  if (
    !validCallBudgetValue(mission, 10000) ||
    !validCallBudgetValue(worker, 100)
  )
    return null;
  return {
    max_model_calls: Number(mission),
    worker_model_calls: Number(worker),
  };
}
