import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  AlertTriangle,
  Check,
  LoaderCircle,
  RotateCcw,
  Save,
  Settings2,
  Webhook,
} from "lucide-react";
import { api } from "./api";
import { ModelPicker } from "./ModelPicker";
import { ModelCallBudgetForm } from "./ModelCallBudgetForm";
import { roles } from "./office";
import { confirmsRegenesis, validModelConfig } from "./modelSettings";
import type {
  ModelConfig,
  RegenesisResult,
  Run,
  WorkspaceSettings as Settings,
} from "./types";
export type SettingsSection = "model" | "connections" | "regenesis";
export function WorkspaceSettings({
  settings,
  loading,
  loadError,
  initialSection,
  onSaved,
  onRegenesis,
  onReload,
  selectedRun,
  onRunUpdated,
}: {
  settings: Settings | null;
  loading: boolean;
  loadError: string;
  initialSection: SettingsSection;
  onSaved: (settings: Settings) => void;
  onRegenesis: (confirmation: string) => Promise<RegenesisResult>;
  onReload: () => void;
  selectedRun?: Run | null;
  onRunUpdated?: (run: Run) => void;
}) {
  const [section, setSection] = useState<SettingsSection>(initialSection);
  const [draft, setDraft] = useState<ModelConfig | undefined>(
    settings?.model_config,
  );
  const [target, setTarget] = useState("all");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [budgetBusy, setBudgetBusy] = useState(false);
  const [resetVersion, setResetVersion] = useState(0);
  const controlsBusy = busy || budgetBusy;
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const selectedConfig = settings
    ? target === "all"
      ? settings.model_config
      : (settings.agent_model_configs?.[target] ?? settings.model_config)
    : undefined;
  useEffect(() => {
    if (selectedConfig) setDraft({ ...selectedConfig });
  }, [
    target,
    selectedConfig?.provider,
    selectedConfig?.model,
    selectedConfig?.reasoning_effort,
  ]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (
      controlsBusy ||
      !settings ||
      !draft ||
      !validModelConfig(settings, draft)
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const config = { ...draft, model: draft.model.trim() };
      const updated =
        target === "all"
          ? await api.saveModel(config)
          : await api.saveAgentModel(target, config);
      onSaved(updated);
      setNotice(
        target === "all"
          ? "Saved. New missions will use this model."
          : `Saved. New missions will use this model for ${roles.find((role) => role.id === target)?.name ?? target}.`,
      );
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Model settings could not be saved",
      );
    } finally {
      setBusy(false);
    }
  }
  async function removeOverride() {
    if (controlsBusy || target === "all") return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await api.removeAgentModel(target);
      onSaved(updated);
      setNotice("The agent now inherits the default model.");
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The override could not be removed",
      );
    } finally {
      setBusy(false);
    }
  }
  async function reset(event: FormEvent) {
    event.preventDefault();
    if (controlsBusy || !confirmsRegenesis(confirmation)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await onRegenesis(confirmation);
      setTarget("all");
      setDraft({ ...result.settings.model_config });
      setResetVersion((version) => version + 1);
      setConfirmation("");
      setSection("model");
      setNotice(
        `Regenesis complete. ${result.removed_runs} ${result.removed_runs === 1 ? "run was" : "runs were"} removed and startup defaults restored.`,
      );
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Regenesis could not be completed",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="workspace-settings">
      <div
        className="settings-tabs"
        role="tablist"
        aria-label="Settings sections"
      >
        {(
          [
            { id: "model", label: "Model", icon: Settings2 },
            { id: "connections", label: "Connections", icon: Webhook },
            { id: "regenesis", label: "Regenesis", icon: RotateCcw },
          ] as const
        ).map((tab) => (
          <button
            type="button"
            role="tab"
            aria-selected={section === tab.id}
            key={tab.id}
            disabled={controlsBusy}
            onClick={() => {
              setSection(tab.id);
              setError("");
              setNotice("");
            }}
          >
            <tab.icon size={14} />
            {tab.label}
          </button>
        ))}
      </div>
      {section === "model" ? (
        <section
          className="settings-model"
          role="tabpanel"
          aria-label="Model settings"
        >
          <h3>Model for new missions</h3>
          <p>
            Choose the default provider, model, and reasoning effort. Each new
            mission keeps its own snapshot.
          </p>
          {loading && !settings ? (
            <p className="settings-loading">
              <LoaderCircle size={15} className="spin" />
              Loading model settings…
            </p>
          ) : settings && draft ? (
            <>
              <form onSubmit={save}>
                <label>
                  Apply to
                  <select
                    value={target}
                    disabled={controlsBusy}
                    onChange={(event) => {
                      setTarget(event.target.value);
                      setNotice("");
                      setError("");
                    }}
                  >
                    <option value="all">All agents (default)</option>
                    {roles.map((role) => (
                      <option key={role.id} value={role.id}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                </label>
                {target === "tools_rd_lead" && (
                  <p className="agent-access-note">
                    Only Planner or Engineering lead may call this agent.
                  </p>
                )}
                {["backend_coder", "system_architect"].includes(target) && (
                  <p className="agent-access-note">
                    Dynamic Engineering specialists inherit their declared base
                    role’s model selection.
                  </p>
                )}
                {target !== "all" && (
                  <div className="agent-model-inheritance">
                    <p>
                      {settings.agent_model_configs?.[target]
                        ? "This agent has a custom model selection for new missions."
                        : "This agent inherits the default model. Saving creates an override for new missions."}
                    </p>
                    {settings.agent_model_configs?.[target] && (
                      <button
                        className="text-button"
                        type="button"
                        disabled={controlsBusy}
                        onClick={() => void removeOverride()}
                      >
                        Use default model
                      </button>
                    )}
                  </div>
                )}
                <ModelPicker
                  settings={settings}
                  value={draft}
                  onChange={setDraft}
                  disabled={controlsBusy}
                />
                <div className="settings-runtime-note">
                  <span>
                    Triage:{" "}
                    {settings.triage.configured
                      ? settings.triage.model
                      : "Not configured"}
                  </span>
                  <span>Worker timeout: {settings.worker_timeout}s</span>
                  <span>
                    Web search:{" "}
                    {settings.web_search
                      ? `${settings.web_search.provider === "exa" ? "Exa" : "Z.AI MCP"}${settings.web_search.configured ? "" : " · Not configured"}`
                      : "Not reported"}
                  </span>
                </div>
                <button
                  className="primary-button"
                  disabled={controlsBusy || !validModelConfig(settings, draft)}
                >
                  {busy ? (
                    <LoaderCircle size={15} className="spin" />
                  ) : (
                    <Save size={15} />
                  )}
                  {target === "all"
                    ? "Save model settings"
                    : "Save agent model"}
                </button>
              </form>
              {settings.model_call_budget ? (
                <ModelCallBudgetForm
                  key={resetVersion}
                  budget={settings.model_call_budget}
                  disabled={busy}
                  onSaved={onSaved}
                  onBusyChange={setBudgetBusy}
                  selectedRun={selectedRun}
                  onRunUpdated={onRunUpdated}
                />
              ) : (
                <div className="settings-load-error">
                  <p>Call budget settings are unavailable.</p>
                  <button
                    className="text-button"
                    type="button"
                    onClick={onReload}
                  >
                    Reload settings
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className="settings-load-error">
              <p>{loadError || "Model settings are unavailable."}</p>
              <button className="text-button" type="button" onClick={onReload}>
                Try again
              </button>
            </div>
          )}
        </section>
      ) : section === "connections" ? (
        <section
          role="tabpanel"
          aria-label="Connections"
          className="settings-connections"
        >
          <h3>Bring another agent to the office</h3>
          <p className="form-help">
            Project activity from your tools into the connected workspace.
            Source-scoped event IDs keep repeated deliveries separate from new
            activity.
          </p>
          <div className="integration-endpoint">
            <span>POST</span>
            <code>/api/integrations/events</code>
          </div>
          <pre className="code-block">
            {JSON.stringify(
              {
                event_id: "agent-event-001",
                source: "my-integration",
                agent_id: "design-agent",
                activity: "writing",
                summary: "Preparing design notes",
                timestamp: new Date().toISOString(),
                data: {},
              },
              null,
              2,
            )}
          </pre>
          <p className="form-help">
            External events update agent activity only. They cannot approve work
            or control internal runs. Credentials remain server-side.
          </p>
        </section>
      ) : (
        <section
          role="tabpanel"
          aria-label="Regenesis reset"
          className="settings-regenesis"
        >
          <div className="regenesis-title">
            <AlertTriangle size={19} />
            <div>
              <h3>Reset the harness</h3>
              <p>Regenesis permanently clears all harness-managed data.</p>
            </div>
          </div>
          <ul className="regenesis-scope">
            <li>
              All runs, artifacts, events, checkpoints, and saved settings in
              the harness database.
            </li>
            <li>Harness-managed files and run workspaces on disk.</li>
            <li>
              Provider, model, and call budget settings return to startup
              defaults.
            </li>
          </ul>
          <p className="regenesis-retained">
            The app and <code>.env</code> stay in place. External workspaces you
            selected are kept, including files written there.
          </p>
          <form onSubmit={reset}>
            <label>
              Type REGENESIS to confirm
              <input
                autoComplete="off"
                spellCheck={false}
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                placeholder="REGENESIS"
                disabled={busy}
              />
            </label>
            <button
              className="danger-button"
              disabled={busy || !confirmsRegenesis(confirmation)}
            >
              {busy ? (
                <LoaderCircle size={15} className="spin" />
              ) : (
                <RotateCcw size={15} />
              )}
              {busy
                ? "Stopping workers and resetting…"
                : "Reset all harness data"}
            </button>
          </form>
        </section>
      )}
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
    </div>
  );
}
