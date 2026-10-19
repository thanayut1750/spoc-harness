import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import { Check, LoaderCircle, Save } from "lucide-react";
import { api } from "./api";
import { parseCallBudget, validCallBudgetValue } from "./modelCallBudget";
import type { ModelCallBudget, WorkspaceSettings } from "./types";

export function ModelCallBudgetForm({
  budget,
  disabled,
  onSaved,
  onBusyChange,
}: {
  budget: ModelCallBudget;
  disabled: boolean;
  onSaved: (settings: WorkspaceSettings) => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const [mission, setMission] = useState(String(budget.max_model_calls));
  const [worker, setWorker] = useState(String(budget.worker_model_calls));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const helpId = useId();
  const parsed = parseCallBudget(mission, worker);
  useEffect(() => {
    setMission(String(budget.max_model_calls));
    setWorker(String(budget.worker_model_calls));
  }, [budget.max_model_calls, budget.worker_model_calls]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!parsed || disabled || saving) return;
    setSaving(true);
    onBusyChange(true);
    setError("");
    setNotice("");
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

  return (
    <section className="settings-call-budget" aria-label="Model call budget">
      <h3>Model call budget</h3>
      <p>
        Workspace-wide limits for new missions, across all model choices.
        Existing missions keep their recorded limits. The mission budget covers
        all generative model requests, including reviews and retries.
      </p>
      <form onSubmit={save}>
        <div className="call-budget-fields">
          <div>
            <label htmlFor={`${helpId}-mission-input`}>
              Model calls per mission
            </label>
            <input
              id={`${helpId}-mission-input`}
              type="number"
              inputMode="numeric"
              min={1}
              max={10000}
              step={1}
              required
              value={mission}
              disabled={disabled || saving}
              aria-describedby={`${helpId}-mission`}
              aria-invalid={!validCallBudgetValue(mission, 10000)}
              onChange={(event) => {
                setMission(event.target.value);
                setNotice("");
              }}
            />
            <small id={`${helpId}-mission`}>
              1–10,000 calls shared by all agents in one mission.
            </small>
          </div>
          <div>
            <label htmlFor={`${helpId}-worker-input`}>
              Agent model turns per invocation
            </label>
            <input
              id={`${helpId}-worker-input`}
              type="number"
              inputMode="numeric"
              min={1}
              max={100}
              step={1}
              required
              value={worker}
              disabled={disabled || saving}
              aria-describedby={`${helpId}-worker`}
              aria-invalid={!validCallBudgetValue(worker, 100)}
              onChange={(event) => {
                setWorker(event.target.value);
                setNotice("");
              }}
            />
            <small id={`${helpId}-worker`}>
              1–100 turns each time an agent runs, within the mission budget.
            </small>
          </div>
        </div>
        <button
          className="primary-button"
          disabled={disabled || saving || !parsed}
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
    </section>
  );
}
