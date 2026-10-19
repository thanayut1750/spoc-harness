import { useEffect, useId, useRef, useState } from "react";
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
  const [mission, setMission] = useState(String(budget.max_model_calls ?? 100));
  const [worker, setWorker] = useState(String(budget.worker_model_calls ?? 12));
  const finiteMission = useRef(String(budget.max_model_calls ?? 100));
  const finiteWorker = useRef(String(budget.worker_model_calls ?? 12));
  const [missionUnlimited, setMissionUnlimited] = useState(
    budget.max_model_calls === null,
  );
  const [workerUnlimited, setWorkerUnlimited] = useState(
    budget.worker_model_calls === null,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const helpId = useId();
  const parsed = parseCallBudget(mission, worker, {
    missionUnlimited,
    workerUnlimited,
  });
  useEffect(() => {
    if (budget.max_model_calls !== null) {
      finiteMission.current = String(budget.max_model_calls);
      setMission(String(budget.max_model_calls));
    }
    if (budget.worker_model_calls !== null) {
      finiteWorker.current = String(budget.worker_model_calls);
      setWorker(String(budget.worker_model_calls));
    }
    setMissionUnlimited(budget.max_model_calls === null);
    setWorkerUnlimited(budget.worker_model_calls === null);
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
        all generative model requests, including reviews and retries. No limit
        removes the selected model cap; timeouts, tool-call and revision limits
        still apply.
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
              required={!missionUnlimited}
              value={missionUnlimited ? "" : mission}
              placeholder={missionUnlimited ? "No limit" : undefined}
              disabled={disabled || saving || missionUnlimited}
              aria-describedby={`${helpId}-mission`}
              aria-invalid={
                !missionUnlimited && !validCallBudgetValue(mission, 10000)
              }
              onChange={(event) => {
                setMission(event.target.value);
                if (validCallBudgetValue(event.target.value, 10000))
                  finiteMission.current = event.target.value;
                setNotice("");
              }}
            />
            <label className="call-budget-unlimited">
              <input
                type="checkbox"
                aria-label="No limit for model calls per mission"
                checked={missionUnlimited}
                disabled={disabled || saving}
                onChange={(event) => {
                  setMissionUnlimited(event.target.checked);
                  if (
                    !event.target.checked &&
                    !validCallBudgetValue(mission, 10000)
                  )
                    setMission(finiteMission.current);
                  setNotice("");
                }}
              />
              No limit
            </label>
            <small id={`${helpId}-mission`}>
              When limited: 1–10,000 calls shared by all agents in one mission.
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
              required={!workerUnlimited}
              value={workerUnlimited ? "" : worker}
              placeholder={workerUnlimited ? "No limit" : undefined}
              disabled={disabled || saving || workerUnlimited}
              aria-describedby={`${helpId}-worker`}
              aria-invalid={
                !workerUnlimited && !validCallBudgetValue(worker, 100)
              }
              onChange={(event) => {
                setWorker(event.target.value);
                if (validCallBudgetValue(event.target.value, 100))
                  finiteWorker.current = event.target.value;
                setNotice("");
              }}
            />
            <label className="call-budget-unlimited">
              <input
                type="checkbox"
                aria-label="No limit for agent model turns per invocation"
                checked={workerUnlimited}
                disabled={disabled || saving}
                onChange={(event) => {
                  setWorkerUnlimited(event.target.checked);
                  if (
                    !event.target.checked &&
                    !validCallBudgetValue(worker, 100)
                  )
                    setWorker(finiteWorker.current);
                  setNotice("");
                }}
              />
              No limit
            </label>
            <small id={`${helpId}-worker`}>
              When limited: 1–100 turns each time an agent runs, within any
              mission budget.
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
