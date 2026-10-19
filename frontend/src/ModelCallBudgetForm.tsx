import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Check, LoaderCircle, Save } from "lucide-react";
import { api } from "./api";
import {
  canApplyCallBudget,
  formatCallLimit,
  matchesSavedCallBudget,
  normalizeCallBudget,
  parseCallBudget,
  validCallBudgetValue,
} from "./modelCallBudget";
import type { ModelCallBudget, Run, WorkspaceSettings } from "./types";

const fields = [
  {
    key: "max_model_calls",
    label: "Model calls per mission",
    maximum: 10000,
    initial: 100,
    help: "When limited: 1–10,000 calls shared by all agents in one mission.",
  },
  {
    key: "worker_model_calls",
    label: "Agent model turns per invocation",
    maximum: 100,
    initial: 12,
    help: "When limited: 1–100 turns each time an agent runs, within any mission budget.",
  },
  {
    key: "max_tool_calls",
    label: "Tool calls per mission",
    maximum: 100000,
    initial: 200,
    help: "When limited: 1–100,000 tool calls shared by all agents in one mission.",
  },
] as const;
type BudgetKey = (typeof fields)[number]["key"];

export function ModelCallBudgetForm({
  budget,
  disabled,
  onSaved,
  onBusyChange,
  selectedRun,
  onRunUpdated,
}: {
  budget: ModelCallBudget;
  disabled: boolean;
  onSaved: (settings: WorkspaceSettings) => void;
  onBusyChange: (busy: boolean) => void;
  selectedRun?: Run | null;
  onRunUpdated?: (run: Run) => void;
}) {
  const saved = normalizeCallBudget(budget);
  const [draft, setDraft] = useState(
    () =>
      Object.fromEntries(
        fields.map((field) => [
          field.key,
          String(saved[field.key] ?? field.initial),
        ]),
      ) as Record<BudgetKey, string>,
  );
  const finiteDraft = useRef({ ...draft });
  const [unlimited, setUnlimited] = useState(
    () =>
      Object.fromEntries(
        fields.map((field) => [field.key, saved[field.key] === null]),
      ) as Record<BudgetKey, boolean>,
  );
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [applyError, setApplyError] = useState("");
  const [applyNotice, setApplyNotice] = useState("");
  const helpId = useId();
  const busy = saving || applying;
  const parsed = parseCallBudget(
    draft.max_model_calls,
    draft.worker_model_calls,
    {
      missionUnlimited: unlimited.max_model_calls,
      workerUnlimited: unlimited.worker_model_calls,
      toolCalls: draft.max_tool_calls,
      toolUnlimited: unlimited.max_tool_calls,
    },
  );
  const hasUnsavedBudget = !matchesSavedCallBudget(parsed, saved);
  useEffect(() => {
    const next = normalizeCallBudget(budget);
    setDraft((current) => {
      const updated = { ...current };
      for (const field of fields)
        if (next[field.key] !== null) {
          updated[field.key] = String(next[field.key]);
          finiteDraft.current[field.key] = updated[field.key];
        }
      return updated;
    });
    setUnlimited({
      max_model_calls: next.max_model_calls === null,
      worker_model_calls: next.worker_model_calls === null,
      max_tool_calls: next.max_tool_calls === null,
    });
  }, [saved.max_model_calls, saved.worker_model_calls, saved.max_tool_calls]);
  useEffect(() => {
    setApplyError("");
    setApplyNotice("");
  }, [selectedRun?.run_id]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!parsed || disabled || busy) return;
    setSaving(true);
    onBusyChange(true);
    setError("");
    setNotice("");
    setApplyNotice("");
    try {
      const updated = await api.saveCallBudget(parsed);
      onSaved(updated);
      setNotice("Saved. New missions will use this call budget.");
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The call budget could not be saved.",
      );
    } finally {
      setSaving(false);
      onBusyChange(false);
    }
  }

  async function applySavedBudget() {
    if (
      !canApplyCallBudget(selectedRun) ||
      !selectedRun ||
      disabled ||
      busy ||
      hasUnsavedBudget
    )
      return;
    setApplying(true);
    onBusyChange(true);
    setApplyError("");
    setApplyNotice("");
    try {
      const updated = await api.updateRunBudgets(selectedRun.run_id, saved);
      onRunUpdated?.(updated);
      setApplyNotice(
        "Saved budgets applied. The mission has not resumed and usage counters are unchanged.",
      );
    } catch (failure) {
      setApplyError(
        failure instanceof Error
          ? failure.message
          : "The mission budgets could not be updated.",
      );
    } finally {
      setApplying(false);
      onBusyChange(false);
    }
  }

  return (
    <section className="settings-call-budget" aria-label="Call budgets">
      <h3>Call budgets</h3>
      <p>
        Workspace-wide defaults for new missions, across all model choices. The
        model-call budget includes reviews and retries. No limit removes only
        the selected call cap; timeouts and revision limits still apply.
        Existing missions keep their recorded limits until explicitly updated.
      </p>
      <form onSubmit={save}>
        <div className="call-budget-fields">
          {fields.map((field) => (
            <div key={field.key}>
              <label htmlFor={`${helpId}-${field.key}-input`}>
                {field.label}
              </label>
              <input
                id={`${helpId}-${field.key}-input`}
                type="number"
                inputMode="numeric"
                min={1}
                max={field.maximum}
                step={1}
                required={!unlimited[field.key]}
                value={unlimited[field.key] ? "" : draft[field.key]}
                placeholder={unlimited[field.key] ? "No limit" : undefined}
                disabled={disabled || busy || unlimited[field.key]}
                aria-describedby={`${helpId}-${field.key}-help`}
                aria-invalid={
                  !unlimited[field.key] &&
                  !validCallBudgetValue(draft[field.key], field.maximum)
                }
                onChange={(event) => {
                  const value = event.target.value;
                  setDraft((current) => ({ ...current, [field.key]: value }));
                  if (validCallBudgetValue(value, field.maximum))
                    finiteDraft.current[field.key] = value;
                  setNotice("");
                }}
              />
              <label className="call-budget-unlimited">
                <input
                  type="checkbox"
                  aria-label={`No limit for ${field.label.toLowerCase()}`}
                  checked={unlimited[field.key]}
                  disabled={disabled || busy}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setUnlimited((current) => ({
                      ...current,
                      [field.key]: checked,
                    }));
                    if (
                      !checked &&
                      !validCallBudgetValue(draft[field.key], field.maximum)
                    )
                      setDraft((current) => ({
                        ...current,
                        [field.key]: finiteDraft.current[field.key],
                      }));
                    setNotice("");
                  }}
                />
                No limit
              </label>
              <small id={`${helpId}-${field.key}-help`}>{field.help}</small>
            </div>
          ))}
        </div>
        <button
          className="primary-button"
          disabled={disabled || busy || !parsed}
        >
          {saving ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <Save size={15} />
          )}
          {saving ? "Saving call budget…" : "Save call budget"}
        </button>
      </form>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="settings-notice" role="status">
          <Check size={15} />
          {notice}
        </p>
      )}
      {selectedRun && (
        <section
          className="mission-call-budget"
          aria-label="Selected mission call budgets"
        >
          <h4>Selected mission · {selectedRun.run_id.slice(0, 8)}</h4>
          <p className="budget-mission-name">{selectedRun.user_request}</p>
          <dl>
            <div>
              <dt>Model calls</dt>
              <dd>
                {selectedRun.model_calls ?? "Not reported"} used · limit:{" "}
                {formatCallLimit(selectedRun.limits?.max_model_calls)}
              </dd>
            </div>
            <div>
              <dt>Agent model turns per invocation</dt>
              <dd>{formatCallLimit(selectedRun.limits?.worker_model_calls)}</dd>
            </div>
            <div>
              <dt>Tool calls</dt>
              <dd>
                {selectedRun.tool_calls ?? "Not reported"} used · limit:{" "}
                {formatCallLimit(selectedRun.limits?.max_tool_calls)}
              </dd>
            </div>
          </dl>
          {canApplyCallBudget(selectedRun) ? (
            <>
              <p>
                Saved workspace budgets: model calls{" "}
                {formatCallLimit(saved.max_model_calls)}, agent turns{" "}
                {formatCallLimit(saved.worker_model_calls)}, tool calls{" "}
                {formatCallLimit(saved.max_tool_calls)}. Applying these values
                does not resume the mission or reset its usage.
              </p>
              {hasUnsavedBudget && (
                <p>Save changes before applying them to this mission.</p>
              )}
              <button
                type="button"
                className="secondary-button"
                disabled={disabled || busy || hasUnsavedBudget}
                onClick={() => void applySavedBudget()}
              >
                {applying && <LoaderCircle size={15} className="spin" />}
                {applying
                  ? "Applying saved budgets…"
                  : "Apply saved budgets to this mission"}
              </button>
            </>
          ) : (
            <p>
              Budgets can be updated while this mission is paused, awaiting
              review, or failed. This does not change other missions.
            </p>
          )}
          {applyError && (
            <p className="form-error" role="alert">
              {applyError}
            </p>
          )}
          {applyNotice && (
            <p className="settings-notice" role="status">
              <Check size={15} />
              {applyNotice}
            </p>
          )}
        </section>
      )}
    </section>
  );
}
