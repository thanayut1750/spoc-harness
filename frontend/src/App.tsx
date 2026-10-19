import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity as ActivityIcon,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCheck,
  ChevronDown,
  Circle,
  Code2,
  ExternalLink,
  FileText,
  GitBranch,
  Layers3,
  LayoutGrid,
  List,
  LoaderCircle,
  MessageSquare,
  Pause,
  Play,
  Plus,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  Square,
  Terminal,
  Users,
  Webhook,
  X,
} from "lucide-react";
import { api } from "./api";
import { ArtifactFiles } from "./ArtifactFiles";
import { scopedAgentArtifacts } from "./artifactScopes";
import { ReviewEvidence } from "./ReviewEvidence";
import {
  actionCtas,
  actionLabels,
  allowedActions,
  reviewFocus,
  reviewReason,
  recommendedAction,
  retryContext,
  retryDirective,
  reviewPresentation,
  reviewOperation,
} from "./review";
import { OfficeCanvas } from "./OfficeCanvas";
import { ModelPicker } from "./ModelPicker";
import { WorkspaceSettings } from "./WorkspaceSettings";
import type { SettingsSection } from "./WorkspaceSettings";
import { agentModelSelection, validModelConfig } from "./modelSettings";
import {
  activeActivities,
  activityLabels,
  displayActivity,
  pretty,
  progressStatus,
  roleFor,
  routingSummary,
  terminalStatuses,
} from "./office";
import { useOffice } from "./useOffice";
import { agentActivityScope } from "./activityHistory";
import { useActivityHistory } from "./useActivityHistory";
import type {
  ActivityEvent,
  AgentActivity,
  Artifact,
  ResumeInput,
  ReviewAction,
  Run,
  RunInput,
  ModelConfig,
  RegenesisResult,
  WorkspaceSettings as SettingsData,
  ActivitySubscription,
} from "./types";

const statusTone = (status: string) =>
  ["completed", "succeeded", "passed", "success"].includes(status)
    ? "success"
    : [
          "failed",
          "error",
          "blocked",
          "needs_review",
          "awaiting_review",
          "review",
          "paused",
        ].includes(status)
      ? "warning"
      : "neutral";
function Status({ status }: { status: string }) {
  return (
    <span className={`status ${statusTone(status)}`}>
      <i />
      {pretty(status)}
    </span>
  );
}
function Stamp({ date }: { date: string }) {
  const parsed = new Date(date);
  return (
    <time dateTime={date}>
      {Number.isNaN(parsed.valueOf())
        ? "—"
        : parsed.toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })}
    </time>
  );
}
function stringify(value: unknown) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
function Modal({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
  className = "",
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  className?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      aria-labelledby={titleId}
      className={`modal ${wide ? "modal-wide" : ""} ${className}`}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <div className="modal-heading">
        <div>
          <span className="eyebrow">SPOC WORKSPACE</span>
          <h2 id={titleId}>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <button
          className="icon-button"
          aria-label="Close dialog"
          onClick={onClose}
        >
          <X size={19} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
function MissionModal({
  settings,
  onClose,
  onSubmit,
  busy,
  error,
}: {
  settings: SettingsData | null;
  onClose: () => void;
  onSubmit: (input: RunInput) => void;
  busy: boolean;
  error: string;
}) {
  const [request, setRequest] = useState("");
  const [modelConfig, setModelConfig] = useState<ModelConfig | undefined>(
    settings?.model_config,
  );
  useEffect(() => {
    if (!modelConfig && settings) setModelConfig({ ...settings.model_config });
  }, [settings, modelConfig]);
  const [workspace, setWorkspace] = useState("");
  const [mission, setMission] = useState("");
  const [prohibited, setProhibited] = useState("");
  const [rules, setRules] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({
      user_request: request.trim(),
      ...(modelConfig
        ? { model_config: { ...modelConfig, model: modelConfig.model.trim() } }
        : {}),
      ...(workspace.trim() ? { workspace_path: workspace.trim() } : {}),
      ...(mission.trim() || prohibited.trim() || rules.trim()
        ? {
            constitution: {
              mission_statement: mission.trim() || request.trim(),
              prohibited_actions: prohibited
                .split("\n")
                .map((v) => v.trim())
                .filter(Boolean),
              compliance_rules: rules
                .split("\n")
                .map((v) => v.trim())
                .filter(Boolean),
              max_revision_loops: 2,
            },
          }
        : {}),
    });
  }
  return (
    <Modal
      title="Give the office a mission"
      subtitle="One objective. A coordinated team. Measurable results."
      onClose={onClose}
      wide
    >
      <form onSubmit={submit}>
        <label>
          What should the organization accomplish?
          <textarea
            autoFocus
            required
            minLength={3}
            rows={4}
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            placeholder="Research a problem, design a solution, and build something useful…"
          />
        </label>
        <label>
          Working directory <span className="optional">optional</span>
          <input
            value={workspace}
            onChange={(e) => setWorkspace(e.target.value)}
            placeholder="Use a dedicated workspace for this run"
          />
          <small>
            Engineering commands execute on this computer in the chosen
            directory.
          </small>
        </label>
        {settings && modelConfig ? (
          <details className="mission-model-settings">
            <summary>
              <Settings2 size={14} />
              <span>
                <strong>{modelConfig.model}</strong>
                <small>
                  {settings.providers.find(
                    (provider) => provider.id === modelConfig.provider,
                  )?.label ?? modelConfig.provider}{" "}
                  · {modelConfig.reasoning_effort} reasoning
                  {Object.keys(settings.agent_model_configs ?? {}).length
                    ? ` · ${Object.keys(settings.agent_model_configs ?? {}).length} agent overrides`
                    : ""}
                </small>
              </span>
              <span className="change-model-label">Change model</span>
              <ChevronDown size={13} />
            </summary>
            <p className="model-snapshot-note">
              This selection is saved with the mission. Later default changes
              apply to new missions.
            </p>
            <ModelPicker
              settings={settings}
              value={modelConfig}
              onChange={setModelConfig}
              disabled={busy}
            />
          </details>
        ) : (
          <p className="model-snapshot-note">
            The server’s saved model configuration will be captured when this
            mission is created.
          </p>
        )}
        <details className="constitution-options">
          <summary>
            <ShieldCheck size={15} /> Constitution & boundaries{" "}
            <ChevronDown size={14} />
          </summary>
          <label>
            Mission statement
            <input
              value={mission}
              onChange={(e) => setMission(e.target.value)}
              placeholder="Defaults to your objective"
            />
          </label>
          <div className="form-grid">
            <label>
              Prohibited actions
              <textarea
                rows={3}
                value={prohibited}
                onChange={(e) => setProhibited(e.target.value)}
                placeholder="One action per line"
              />
            </label>
            <label>
              Compliance rules
              <textarea
                rows={3}
                value={rules}
                onChange={(e) => setRules(e.target.value)}
                placeholder="One rule per line"
              />
            </label>
          </div>
        </details>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-footer">
          <span>
            <GitBranch size={14} /> Strategy → specialists → review
          </span>
          <button
            className="primary-button"
            disabled={
              busy ||
              request.trim().length < 3 ||
              (!!settings &&
                !!modelConfig &&
                !validModelConfig(settings, modelConfig))
            }
          >
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <ArrowRight size={16} />
            )}{" "}
            Launch mission
          </button>
        </div>
      </form>
    </Modal>
  );
}
function ReviewModal({
  run,
  artifacts,
  events,
  onClose,
  onSubmit,
  busy,
  error,
}: {
  run: Run;
  artifacts: Artifact[];
  events: ActivityEvent[];
  onClose: () => void;
  onSubmit: (input: ResumeInput) => void;
  busy: boolean;
  error: string;
}) {
  const options = allowedActions(run);
  const recommended = recommendedAction(run);
  const presentation = reviewPresentation(run);
  const operation = reviewOperation(run);
  const focus = reviewFocus(run, events);
  const results =
    run.objectives?.flatMap((objective) => objective.key_results) ?? [];
  const initialKr = focus.blocked[0]?.kr_id ?? run.review?.kr_id ?? "";
  const initialDefinition = results.find(
    (result) => result.kr_id === initialKr,
  );
  const [action, setAction] = useState<ReviewAction>(recommended);
  const selectedAction = options.includes(action) ? action : recommended;
  const [context, setContext] = useState("");
  const [kr, setKr] = useState(initialKr);
  const [description, setDescription] = useState(
    initialDefinition?.description ?? "",
  );
  const [criteria, setCriteria] = useState(
    initialDefinition?.acceptance_criteria.join("\n") ?? "",
  );
  const guidanceRequired =
    selectedAction === "provide_context" && presentation.requiresGuidance;
  const primaryLabel =
    selectedAction === "provide_context" && presentation.requiresGuidance
      ? "Send guidance and retry"
      : actionCtas[selectedAction];
  const mission = run.review?.context?.mission ?? run.user_request;
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!run.review || !options.length || (guidanceRequired && !context.trim()))
      return;
    const sentContext =
      selectedAction === "provide_context"
        ? guidanceRequired
          ? context.trim()
          : retryContext(run, context)
        : context.trim();
    onSubmit({
      interrupt_id: run.review.interrupt_id,
      action: selectedAction,
      ...(sentContext ? { context: sentContext } : {}),
      ...(selectedAction === "revise_kr"
        ? {
            kr_id: kr,
            description: description.trim(),
            acceptance_criteria: criteria
              .split("\n")
              .map((criterion) => criterion.trim())
              .filter(Boolean),
          }
        : {}),
    });
  }
  const descriptions: Partial<Record<ReviewAction, string>> = {
    provide_context: presentation.requiresGuidance
      ? presentation.policyIssue
        ? "Tell the team how to continue within the rules."
        : "Answer the team's question so work can continue."
      : retryDirective,
    revise_kr: "Edit what a successful result should include.",
    retry_operation: "Run the interrupted command one more time.",
    continue: "Continue from the saved pause.",
  };
  return (
    <Modal
      title="How should the team continue?"
      onClose={onClose}
      className="review-modal review-compact"
    >
      <div className="review-mission-line">
        <span>Mission</span>
        <p title={mission}>{mission}</p>
      </div>
      <div
        className={`review-brief ${presentation.policyIssue || presentation.unknownOperation ? "review-brief-warning" : ""}`}
      >
        <ShieldCheck size={17} />
        <div>
          <p>{presentation.summary}</p>
          {presentation.warning && (
            <p className="review-important-note">{presentation.warning}</p>
          )}
        </div>
      </div>
      {presentation.unknownOperation && (
        <div className="review-operation">
          <span>Command to run again</span>
          <pre>
            {operation.command ??
              "The command text is unavailable in this saved review. Inspect its evidence before choosing to run it again."}
          </pre>
          {operation.cwd && <small>Folder: {operation.cwd}</small>}
        </div>
      )}
      <form className="review-simple-form" onSubmit={submit}>
        <fieldset className="review-choices">
          <legend>Choose the next step</legend>
          {options
            .filter((option) => option !== "abort")
            .map((option) => (
              <label
                className={`review-choice ${selectedAction === option ? "selected" : ""}`}
                key={option}
              >
                <input
                  type="radio"
                  name="review-action"
                  value={option}
                  checked={selectedAction === option}
                  onChange={() => setAction(option)}
                />
                <span>
                  <span className="review-choice-title">
                    {option === "provide_context" &&
                    presentation.requiresGuidance
                      ? "Give guidance"
                      : actionLabels[option]}
                    {option === recommended &&
                      !presentation.unknownOperation &&
                      !presentation.sourceUnavailable &&
                      !presentation.workerTimeout &&
                      !presentation.usageLimit && <small>Recommended</small>}
                  </span>
                  <span className="review-choice-description">
                    {descriptions[option]}
                  </span>
                </span>
              </label>
            ))}
        </fieldset>
        {guidanceRequired && (
          <label className="required-guidance">
            What should the team do differently?
            <textarea
              rows={3}
              required
              value={context}
              onChange={(event) => setContext(event.target.value)}
              placeholder={
                presentation.policyIssue
                  ? "Explain how the team should complete the task while following the rule…"
                  : "Provide the missing detail or answer the question above…"
              }
            />
          </label>
        )}
        {selectedAction === "provide_context" &&
          !presentation.requiresGuidance && (
            <details className="review-add-note">
              <summary>
                {presentation.sourceUnavailable
                  ? "Add instructions or an alternative source"
                  : "Add instructions (optional)"}
              </summary>
              <label>
                {presentation.sourceUnavailable
                  ? "Instructions or source URL"
                  : "Additional instructions"}
                <textarea
                  rows={3}
                  value={context}
                  onChange={(event) => setContext(event.target.value)}
                  placeholder={
                    presentation.sourceUnavailable
                      ? "Add a source URL, explain an access fix, or suggest another approach…"
                      : "Add a specific correction or useful information…"
                  }
                />
              </label>
            </details>
          )}
        {selectedAction === "revise_kr" && (
          <div className="review-advanced">
            <label>
              Task to update
              <select
                required
                value={kr}
                onChange={(event) => {
                  setKr(event.target.value);
                  const definition = results.find(
                    (result) => result.kr_id === event.target.value,
                  );
                  setDescription(definition?.description ?? "");
                  setCriteria(definition?.acceptance_criteria.join("\n") ?? "");
                }}
              >
                <option value="">Select a task</option>
                {results.map((result, index) => (
                  <option value={result.kr_id} key={result.kr_id}>
                    Task {index + 1}: {result.description}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Updated task
              <textarea
                required
                rows={2}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <label>
              Requirements, one per line
              <textarea
                required
                rows={3}
                value={criteria}
                onChange={(event) => setCriteria(event.target.value)}
              />
            </label>
            <p>
              Changed requirements will be checked again. Any dependent work
              will be reviewed again too.
            </p>
          </div>
        )}
        {selectedAction === "abort" && (
          <div className="review-stop-confirm">
            <p>
              Stop this run? Existing files and evidence will remain available.
            </p>
          </div>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="review-simple-footer">
          <div>
            {options.includes("abort") && (
              <button
                className="text-button stop-run-choice"
                type="button"
                onClick={() =>
                  setAction(selectedAction === "abort" ? recommended : "abort")
                }
              >
                {selectedAction === "abort" ? "Back to options" : "Stop run"}
              </button>
            )}
          </div>
          <button
            className={
              selectedAction === "abort" ? "danger-button" : "primary-button"
            }
            disabled={
              busy ||
              !run.review ||
              !options.length ||
              (guidanceRequired && !context.trim())
            }
          >
            {busy ? (
              <LoaderCircle size={15} className="spin" />
            ) : selectedAction === "abort" ? (
              <Square size={12} />
            ) : (
              <Play size={14} />
            )}{" "}
            {primaryLabel}
          </button>
        </div>
      </form>
      <details className="review-details">
        <summary>
          <FileText size={14} />
          Review evidence and history
          <ChevronDown size={13} />
        </summary>
        <ReviewEvidence run={run} files={artifacts} events={events} />
      </details>
    </Modal>
  );
}
function Pyramid({ run }: { run: Run | null }) {
  const results = run?.objectives?.flatMap((o) => o.key_results) ?? [];
  const passed = results.filter((r) =>
    ["passed", "completed"].includes(progressStatus(run?.progress?.[r.kr_id])),
  ).length;
  return (
    <>
      <div className="panel-label">
        <Layers3 size={15} />
        <span>Strategic pyramid</span>
        <span className="tiny-count">{results.length} KRs</span>
      </div>
      <div className="pyramid-art" aria-hidden="true">
        <div>CONSTITUTION</div>
        <div>OBJECTIVES</div>
        <div>KEY RESULTS</div>
        <div>WORK PACKAGES</div>
      </div>
      <section className="constitution-card">
        <div>
          <ShieldCheck size={14} />
          <span>Constitution</span>
          <span className="locked-label">FIXED</span>
        </div>
        <p>
          {run?.constitution?.mission_statement ??
            "The shared purpose and boundaries that guide every agent."}
        </p>
        {run?.constitution?.prohibited_actions?.length ? (
          <details>
            <summary>
              {run.constitution.prohibited_actions.length} prohibited actions
            </summary>
            <ul>
              {run.constitution.prohibited_actions.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
          </details>
        ) : null}
        {run?.constitution?.compliance_rules?.length ? (
          <details>
            <summary>
              {run.constitution.compliance_rules.length} compliance rules
            </summary>
            <ul>
              {run.constitution.compliance_rules.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>
      <div className="objective-heading">
        <span>OBJECTIVES</span>
        {results.length > 0 && (
          <span>
            {passed}/{results.length} passed
          </span>
        )}
      </div>
      {!run?.objectives?.length ? (
        <div className="sidebar-empty">
          <GitBranch size={22} />
          <p>
            {run
              ? "The planner is preparing the organization’s objectives."
              : "Launch a mission to turn an objective into coordinated work."}
          </p>
        </div>
      ) : (
        run.objectives.map((objective, index) => (
          <section className="objective" key={objective.objective_id}>
            <h3>
              <span>{String(index + 1).padStart(2, "0")}</span>
              {objective.title}
            </h3>
            {objective.key_results.map((result) => {
              const status = progressStatus(run.progress?.[result.kr_id]);
              return (
                <details className="key-result" key={result.kr_id}>
                  <summary>
                    <span className={`kr-dot ${statusTone(status)}`}>
                      {status === "passed" ? <Check size={10} /> : null}
                    </span>
                    <span>{result.description}</span>
                    <ChevronDown size={12} />
                  </summary>
                  <div className="kr-details">
                    <Status status={status} />
                    <p>
                      {pretty(result.target_department)} · v{result.version}
                    </p>
                    <ul>
                      {result.acceptance_criteria.map((criterion) => (
                        <li key={criterion}>{criterion}</li>
                      ))}
                    </ul>
                    {result.dependency_kr_ids.length > 0 && (
                      <p className="dependencies">
                        <GitBranch size={12} />
                        Depends on {result.dependency_kr_ids.join(", ")}
                      </p>
                    )}
                  </div>
                </details>
              );
            })}
          </section>
        ))
      )}
      <div className="sidebar-note">
        <span className="small-dot" />
        {routingSummary(run?.triage)}
      </div>
    </>
  );
}
function Inspector({
  agent,
  events,
  artifacts,
  run,
  onNote,
  busy,
  activityRunId,
  snapshot,
  onHistoryReset,
  subscribe,
}: {
  agent: AgentActivity;
  events: ActivityEvent[];
  artifacts: Artifact[];
  run: Run | null;
  onNote: (content: string) => Promise<boolean>;
  busy: boolean;
  activityRunId?: string;
  snapshot: { generation?: string } | null;
  onHistoryReset: () => void;
  subscribe: ActivitySubscription;
}) {
  const [tab, setTab] = useState("overview");
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);
  const role = roleFor(agent);
  const model = agentModelSelection(agent, run);
  const history = useActivityHistory({
    scope: agentActivityScope(agent, activityRunId),
    liveEvents: events,
    snapshot,
    onReset: onHistoryReset,
    subscribe,
  });
  const relevant = history.events;
  const outcome = agent.kr_id ? run?.outcomes?.[agent.kr_id] : undefined;
  const canGuide =
    !!run &&
    !terminalStatuses.has(run.status) &&
    agent.agent_id !== "tools_rd_lead" &&
    role.kind !== "internal" &&
    (!agent.source || agent.source === "harness");
  const fileScope = scopedAgentArtifacts(agent, artifacts, run?.run_id);
  const files = [...fileScope.owned, ...fileScope.context];
  async function submit(event: FormEvent) {
    event.preventDefault();
    const success = await onNote(note.trim());
    if (!success) return;
    setNote("");
    setSent(true);
    setTimeout(() => setSent(false), 3000);
  }
  return (
    <>
      <div className="panel-label">
        <Users size={15} />
        <span>Agent inspector</span>
        <span className="live-indicator">LIVE STATE</span>
      </div>
      <div className="agent-profile">
        <div
          className="portrait"
          style={{ "--agent-color": role.color } as React.CSSProperties}
        >
          <span />
          <i />
        </div>
        <h2>{role.name}</h2>
        <p>{role.title}</p>
        <Status status={agent.activity} />
      </div>
      <div className="inspector-tabs" role="tablist" aria-label="Agent details">
        {["overview", "activity", "files"].map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            onClick={() => setTab(name)}
          >
            {pretty(name)}
            {name === "files" && files.length > 0 ? (
              <span>{files.length}</span>
            ) : null}
          </button>
        ))}
      </div>
      <div
        className="inspector-content"
        role="tabpanel"
        aria-label={pretty(tab)}
      >
        {tab === "overview" ? (
          <>
            <div className="detail-row">
              <span>Department</span>
              <span className="department-tag" style={{ color: role.color }}>
                {role.department}
              </span>
            </div>
            {role.parent_agent_id && (
              <div className="detail-row">
                <span>Parent</span>
                <span>{roleFor(role.parent_agent_id).name}</span>
              </div>
            )}
            {agent.agent_id === "tools_rd_lead" && (
              <p className="agent-access-note">
                Only Planner or Engineering lead may call this agent.
              </p>
            )}
            {model && (
              <div className="agent-model-note">
                <span className="eyebrow">Model snapshot</span>
                <p>
                  {model.config.provider} / {model.config.model} ·{" "}
                  {model.config.reasoning_effort}
                </p>
                {model.inheritedFrom && (
                  <small>Inherited from {model.inheritedFrom}</small>
                )}
              </div>
            )}
            {agent.source && agent.source !== "harness" && (
              <div className="detail-row">
                <span>Source</span>
                <code>{agent.source}</code>
              </div>
            )}
            <div className="detail-row">
              <span>Key result</span>
              <code>{agent.kr_id ?? "Unassigned"}</code>
            </div>
            <div className="assignment">
              <span className="eyebrow">CURRENT ACTIVITY</span>
              <p>
                {agent.summary ??
                  "At their desk, ready for the next assignment."}
              </p>
              {agent.timestamp && <Stamp date={agent.timestamp} />}
            </div>
            {outcome?.evaluation && (
              <section className="evaluation-card">
                <div>
                  <ShieldCheck size={16} />
                  <h3>Quality evaluation</h3>
                  {typeof outcome.evaluation.score === "number" && (
                    <strong>
                      {Math.round(outcome.evaluation.score * 100)}%
                    </strong>
                  )}
                </div>
                <p>
                  {outcome.evaluation.feedback ??
                    outcome.evaluation.reasoning ??
                    "Evaluation recorded."}
                </p>
                <details>
                  <summary>Full evaluation</summary>
                  <pre>{stringify(outcome.evaluation)}</pre>
                </details>
              </section>
            )}
            {outcome?.deliverable != null && (
              <details className="deliverable">
                <summary>
                  <FileText size={14} /> Latest deliverable
                </summary>
                <pre>{stringify(outcome.deliverable)}</pre>
              </details>
            )}
            <div className="recent-action">
              <div className="section-subtitle">
                <Terminal size={14} />
                <span>Latest tool output</span>
              </div>
              {relevant.find(
                (e) =>
                  e.data?.stdout ||
                  e.data?.stderr ||
                  e.data?.tool_name ||
                  e.data?.output,
              ) ? (
                (() => {
                  const latest = relevant.find(
                    (e) =>
                      e.data?.stdout ||
                      e.data?.stderr ||
                      e.data?.tool_name ||
                      e.data?.output,
                  )!;
                  return (
                    <>
                      <code>{String(latest.data?.tool_name ?? "tool")}</code>
                      <pre>
                        {stringify(
                          latest.data?.stdout ??
                            latest.data?.output ??
                            latest.data?.stderr ??
                            latest.summary,
                        )}
                      </pre>
                    </>
                  );
                })()
              ) : (
                <p className="muted small">
                  Tool output will appear as this agent works.
                </p>
              )}
            </div>
          </>
        ) : tab === "activity" ? (
          <div className="agent-activity">
            <p className="muted small">
              {role.kind === "external"
                ? "Activity from this integration"
                : activityRunId
                  ? "Activity for the selected mission"
                  : "Activity across all missions"}
            </p>
            <ActivityHistoryControls history={history} />
            {relevant.length === 0 && !history.loading && !history.error ? (
              <Empty
                icon={<ActivityIcon size={21} />}
                text="No activity recorded for this agent yet."
              />
            ) : (
              relevant.map((event) => (
                <div className="agent-event" key={event.seq}>
                  <span className={`small-dot ${event.activity}`} />
                  <div>
                    <strong>{activityLabels[event.activity]}</strong>
                    <p>{event.summary}</p>
                    <Stamp date={event.timestamp} />
                    {event.data && Object.keys(event.data).length > 0 && (
                      <details>
                        <summary>Event data</summary>
                        <pre>{stringify(event.data)}</pre>
                      </details>
                    )}
                  </div>
                </div>
              ))
            )}
            {history.hasMore && !history.error && (
              <button
                className="text-button history-more"
                disabled={history.loading}
                onClick={history.loadEarlier}
              >
                {history.loading
                  ? "Loading activity…"
                  : "Load earlier activity"}
              </button>
            )}
          </div>
        ) : (
          <>
            {fileScope.owned.length > 0 && (
              <section
                className="agent-file-scope"
                aria-label="Created by this agent"
              >
                <h3>Created by this agent</h3>
                <ArtifactFiles files={fileScope.owned} />
              </section>
            )}
            {fileScope.context.length > 0 && (
              <section
                className="agent-file-scope"
                aria-label={fileScope.contextLabel}
              >
                <h3>{fileScope.contextLabel}</h3>
                <ArtifactFiles files={fileScope.context} />
              </section>
            )}
            {files.length === 0 && <ArtifactFiles files={[]} />}
          </>
        )}
      </div>
      <form className="guidance" onSubmit={(event) => void submit(event)}>
        <label htmlFor="agent-note">
          <MessageSquare size={14} /> Send guidance
        </label>
        <div>
          <input
            id="agent-note"
            disabled={!canGuide}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="A note for this agent…"
          />
          <button
            aria-label="Send guidance to agent"
            disabled={busy || !canGuide || !note.trim()}
          >
            {sent ? <Check size={15} /> : <Send size={15} />}
          </button>
        </div>
        <small aria-live="polite">
          {sent
            ? "Guidance queued for the next agent boundary."
            : agent.agent_id === "tools_rd_lead"
              ? "Only Planner or Engineering lead may call this agent."
              : role.kind === "internal"
                ? "Internal routing follows the mission requirements."
                : agent.source && agent.source !== "harness"
                  ? "External activity is read-only."
                  : "Delivered at the next applicable work boundary."}
        </small>
      </form>
    </>
  );
}
function ActivityHistoryControls({
  history,
}: {
  history: ReturnType<typeof useActivityHistory>;
}) {
  return history.error ? (
    <div className="history-error" role="alert">
      <p>{history.error}</p>
      <button
        className="text-button history-more"
        onClick={history.retry}
        disabled={history.loading}
      >
        Retry activity
      </button>
    </div>
  ) : history.loading ? (
    <p className="muted small" role="status">
      Loading activity…
    </p>
  ) : null;
}
function Empty({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <div className="empty-state">
      {icon}
      <p>{text}</p>
    </div>
  );
}

export default function App() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selected, setSelected] = useState("executive");
  const [view, setView] = useState<"office" | "list">("office");
  const [modal, setModal] = useState<
    "mission" | "review" | "settings" | "report" | null
  >(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [runsError, setRunsError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [artifactsError, setArtifactsError] = useState("");
  const [modalError, setModalError] = useState("");
  const [filter, setFilter] = useState("");
  const [department, setDepartment] = useState("all");
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsError, setSettingsError] = useState("");
  const [settingsSection, setSettingsSection] =
    useState<SettingsSection>("model");
  const [officeVersion, setOfficeVersion] = useState(0);
  const dataEpoch = useRef(0);
  const selectedRun = useRef(runId);
  useEffect(() => {
    selectedRun.current = runId;
  }, [runId]);
  const refreshRuns = useCallback(async () => {
    const epoch = dataEpoch.current;
    try {
      const items = await api.runs();
      if (epoch !== dataEpoch.current) return;
      setRuns(items);
      setRunsError("");
      setRunId((current) => current || items[0]?.run_id || "");
    } catch (failure) {
      if (epoch !== dataEpoch.current) return;
      setRunsError(
        `Could not load missions: ${failure instanceof Error ? failure.message : "The request failed."}`,
      );
    }
  }, []);
  const refreshDetail = useCallback(async (id: string) => {
    const epoch = dataEpoch.current;
    const [detail, files] = await Promise.allSettled([
      api.run(id),
      api.artifacts(id),
    ]);
    if (epoch !== dataEpoch.current || selectedRun.current !== id) return;
    if (detail.status === "fulfilled") {
      setRun(detail.value);
      setDetailError("");
    } else {
      setDetailError(
        `Could not load mission details: ${detail.reason instanceof Error ? detail.reason.message : "The request failed."}`,
      );
    }
    if (files.status === "fulfilled") {
      setArtifacts(files.value);
      setArtifactsError("");
    } else {
      setArtifactsError(
        `Could not load files: ${files.reason instanceof Error ? files.reason.message : "The request failed."}`,
      );
    }
  }, []);
  const debounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const onEvent = useCallback(
    (event: ActivityEvent) => {
      clearTimeout(debounce.current);
      debounce.current = setTimeout(() => {
        if (event.run_id === selectedRun.current)
          void refreshDetail(event.run_id);
        void refreshRuns();
      }, 250);
    },
    [refreshDetail, refreshRuns],
  );
  const reloadSettings = useCallback(async () => {
    const epoch = dataEpoch.current;
    setSettingsLoading(true);
    setSettingsError("");
    try {
      const result = await api.settings();
      if (epoch === dataEpoch.current) setSettings(result);
    } catch (failure) {
      if (epoch === dataEpoch.current)
        setSettingsError(
          failure instanceof Error
            ? failure.message
            : "Settings are unavailable",
        );
    } finally {
      if (epoch === dataEpoch.current) setSettingsLoading(false);
    }
  }, []);
  useEffect(() => {
    void reloadSettings();
  }, [reloadSettings]);
  const clearClientData = useCallback(() => {
    dataEpoch.current += 1;
    clearTimeout(debounce.current);
    selectedRun.current = "";
    setRunId("");
    setRun(null);
    setRuns([]);
    setArtifacts([]);
    setSelected("executive");
    setView("office");
    setFilter("");
    setDepartment("all");
    setError("");
    setRunsError("");
    setDetailError("");
    setArtifactsError("");
    setModalError("");
    setModal((current) => (current === "settings" ? current : null));
    setOfficeVersion((version) => version + 1);
  }, []);
  const onOfficeReset = useCallback(() => {
    clearClientData();
    void reloadSettings();
    void refreshRuns();
  }, [clearClientData, reloadSettings, refreshRuns]);
  const office = useOffice(onEvent, officeVersion, onOfficeReset);
  async function regenesis(confirmation: string): Promise<RegenesisResult> {
    const result = await api.regenesis(confirmation);
    clearClientData();
    setSettings(result.settings);
    setSettingsError("");
    setSettingsLoading(false);
    return result;
  }
  useEffect(() => {
    void refreshRuns();
    const timer = setInterval(() => void refreshRuns(), 10000);
    return () => {
      clearInterval(timer);
      clearTimeout(debounce.current);
    };
  }, [refreshRuns]);
  useEffect(() => {
    setRun(null);
    setArtifacts([]);
    setDetailError("");
    setArtifactsError("");
    if (!runId) return;
    void refreshDetail(runId);
    const timer = setInterval(() => void refreshDetail(runId), 5000);
    return () => clearInterval(timer);
  }, [runId, refreshDetail]);
  const activityRuns = new Map(runs.map((item) => [item.run_id, item]));
  if (run && !terminalStatuses.has(activityRuns.get(run.run_id)?.status ?? ""))
    activityRuns.set(run.run_id, run);
  const allAgents = Object.values(office.agents).map((agent) =>
    displayActivity(agent, activityRuns.get(agent.run_id ?? "")),
  );
  const agents = allAgents.filter(
    (agent) =>
      (department === "all" ||
        roleFor(agent).department.toLowerCase() === department) &&
      (!filter ||
        roleFor(agent).name.toLowerCase().includes(filter.toLowerCase())),
  );
  const active = allAgents.filter((agent) =>
    activeActivities.has(agent.activity),
  ).length;
  const selectedAgent =
    allAgents.find((agent) => agent.agent_id === selected) ?? allAgents[0];
  const inspectedRun = selectedAgent?.run_id
    ? (activityRuns.get(selectedAgent.run_id) ?? null)
    : run;
  async function perform(operation: () => Promise<unknown>, close = false) {
    setBusy(true);
    setError("");
    setModalError("");
    try {
      await operation();
      await refreshRuns();
      if (selectedRun.current) await refreshDetail(selectedRun.current);
      if (close) setModal(null);
      return true;
    } catch (failure) {
      const message =
        failure instanceof Error ? failure.message : "Request failed";
      if (modal) setModalError(message);
      else setError(message);
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function create(input: RunInput) {
    await perform(async () => {
      const result = await api.create(input);
      selectedRun.current = result.run_id;
      setRunId(result.run_id);
    }, true);
  }
  const reviewRun =
    run && run.status === "paused" && !run.review
      ? {
          ...run,
          review: {
            interrupt_id: "pause",
            kind: "manual_pause",
            message:
              "The workflow is paused. Continue from its saved boundary when ready.",
          },
        }
      : run;
  const canControl = run && !terminalStatuses.has(run.status);
  const needsReview = !!reviewRun?.review;
  const loadError = [runsError, detailError, artifactsError]
    .filter(Boolean)
    .join(" ");
  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#main" aria-label="SPOC home">
          <span className="brand-icon">
            <i />
          </span>
          <strong>SPOC</strong>
          <span className="brand-divider" />
          <span>agent office</span>
        </a>
        <div className="header-center">
          <span className="workspace-dot" />
          Local workspace
          <ChevronDown size={12} />
        </div>
        <div className="header-actions">
          <span
            className={`connection ${office.connection}`}
            title={office.error}
          >
            <i />
            {office.connection === "live"
              ? "Office connected"
              : office.connection === "connecting"
                ? "Connecting"
                : "Reconnecting"}
          </span>
          <button
            className="icon-button"
            aria-label="Workspace settings"
            onClick={() => {
              setSettingsSection("model");
              setModal("settings");
            }}
          >
            <Settings2 size={17} />
          </button>
          <span className="avatar" title="Local operator">
            YOU
          </span>
        </div>
      </header>
      <div className="workspace">
        <aside className="strategy-sidebar" aria-label="Strategic pyramid">
          <div className="sidebar-top">
            <span className="eyebrow">ORGANIZATION</span>
            <button
              className="icon-button"
              aria-label="Create a mission"
              onClick={() => setModal("mission")}
            >
              <Plus size={16} />
            </button>
          </div>
          <Pyramid run={run} />
          <button
            className="integration-card"
            onClick={() => {
              setSettingsSection("connections");
              setModal("settings");
            }}
          >
            <Webhook size={18} />
            <span>
              <strong>Connect your agents</strong>
              <small>Bring your own activity</small>
            </span>
            <ExternalLink size={13} />
          </button>
        </aside>
        <main id="main">
          <section className="mission-bar">
            <div>
              <div className="breadcrumb">
                <span>Workspace</span>
                <span>/</span>
                <span>The office</span>
              </div>
              <div className="mission-title">
                <h1>
                  The office<span className="heading-dot">.</span>
                </h1>
                <span className="edition">LIVE ORGANIZATION</span>
              </div>
            </div>
            <div className="mission-actions">
              <button
                className="primary-button"
                onClick={() => {
                  setModalError("");
                  setModal("mission");
                }}
              >
                <Plus size={16} />
                New mission
              </button>
            </div>
          </section>
          <div className="run-bar">
            <div className="run-selector">
              <GitBranch size={15} />
              <select
                aria-label="Selected mission"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
              >
                <option value="">No mission selected</option>
                {runs.map((item) => (
                  <option value={item.run_id} key={item.run_id}>
                    {item.user_request?.slice(0, 68) || item.run_id}
                  </option>
                ))}
              </select>
            </div>
            <div className="run-controls">
              {run && <Status status={run.status} />}
              <button
                className="icon-button"
                title="Pause at the next work boundary"
                aria-label="Pause mission"
                disabled={
                  !canControl || busy || needsReview || run?.status === "paused"
                }
                onClick={() => void perform(() => api.control(runId, "pause"))}
              >
                <Pause size={15} />
              </button>
              <button
                className="icon-button"
                title="Resume or review mission"
                aria-label="Review and resume mission"
                disabled={!canControl || busy || !needsReview}
                onClick={() => {
                  setModalError("");
                  setModal("review");
                }}
              >
                <Play size={15} />
              </button>
              <button
                className="icon-button"
                title="Cancel mission"
                aria-label="Cancel mission"
                disabled={!canControl || busy}
                onClick={() => void perform(() => api.control(runId, "cancel"))}
              >
                <Square size={13} />
              </button>
            </div>
          </div>
          {run && (run.model_config || run.triage) && (
            <details className="run-configuration">
              <summary>
                <Settings2 size={12} />
                {run.model_config && (
                  <span>
                    {run.model_config.model}
                    <small>{run.model_config.reasoning_effort} reasoning</small>
                  </span>
                )}
                {run.triage && (
                  <span className="triage-mode">
                    Team: {pretty(run.triage.mode)}
                  </span>
                )}
                <ChevronDown size={12} />
              </summary>
              <div>
                {run.model_config && (
                  <p>
                    Model snapshot: {run.model_config.provider} /{" "}
                    {run.model_config.model} ·{" "}
                    {run.model_config.reasoning_effort}
                  </p>
                )}
                {Object.entries(run.agent_model_configs ?? {}).length > 0 && (
                  <div className="run-agent-overrides">
                    <p>Saved agent overrides</p>
                    {Object.entries(run.agent_model_configs ?? {}).map(
                      ([agent, config]) => (
                        <p key={agent}>
                          {roleFor(agent).name}: {config.model} ·{" "}
                          {config.reasoning_effort}
                        </p>
                      ),
                    )}
                  </div>
                )}
                {run.triage && (
                  <>
                    <p>{run.triage.reason}</p>
                    <p>
                      Departments:{" "}
                      {run.triage.departments.map(pretty).join(", ") ||
                        "No departments assigned"}
                    </p>
                  </>
                )}
              </div>
            </details>
          )}
          <details className="mobile-strategy">
            <summary>
              <Layers3 size={14} /> Strategic pyramid <ChevronDown size={13} />
            </summary>
            <Pyramid run={run} />
          </details>
          {(error || loadError) && (
            <div className="error-banner" role="alert">
              <span>{error || loadError}</span>
              <button
                aria-label="Dismiss error"
                onClick={() => {
                  setError("");
                  setRunsError("");
                  setDetailError("");
                  setArtifactsError("");
                }}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {!error &&
            !loadError &&
            office.connection === "offline" &&
            office.error && (
              <div className="error-banner" role="status">
                {office.error}
              </div>
            )}
          {run?.status === "failed" && (
            <div className="failure-banner" role="alert">
              <AlertTriangle size={18} />
              <div>
                <strong>Mission failed</strong>
                <p>
                  {run.error ||
                    "The mission ended before it could finish. Check its recorded activity for details."}
                </p>
                <small>
                  Continue from saved work. Interrupted commands may require
                  review.
                </small>
              </div>
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => void perform(() => api.retry(run.run_id))}
              >
                {busy ? (
                  <LoaderCircle size={15} className="spin" />
                ) : (
                  <Play size={15} />
                )}
                {busy ? "Retrying…" : "Retry mission"}
              </button>
            </div>
          )}
          {needsReview && (
            <button
              className="review-banner"
              onClick={() => {
                setModalError("");
                setModal("review");
              }}
            >
              <ShieldCheck size={18} />
              <span>
                <strong>Choose the next step</strong>
                <span>{reviewRun ? reviewReason(reviewRun) : ""}</span>
              </span>
              <span className="review-action">
                Review <ArrowRight size={14} />
              </span>
            </button>
          )}
          <section className="office-section" aria-label="Agent workspace">
            <div className="office-toolbar">
              <div
                className="view-toggle"
                role="group"
                aria-label="Workspace view"
              >
                <button
                  className={view === "office" ? "selected" : ""}
                  onClick={() => setView("office")}
                >
                  <LayoutGrid size={14} />
                  Office
                </button>
                <button
                  className={view === "list" ? "selected" : ""}
                  onClick={() => setView("list")}
                >
                  <List size={15} />
                  Agents
                </button>
              </div>
              <div className="office-metrics">
                <span>
                  <i className="active-dot" />
                  {active} working
                </span>
                <span>{allAgents.length} agents</span>
              </div>
              <label className="agent-search">
                <Search size={14} />
                <input
                  aria-label="Search agents"
                  placeholder="Find an agent"
                  value={filter}
                  onChange={(e) => {
                    setFilter(e.target.value);
                    if (e.target.value) setView("list");
                  }}
                />
              </label>
            </div>
            <div className="office-body">
              {view === "office" ? (
                <OfficeCanvas
                  agents={allAgents}
                  recordedAgents={Object.values(office.agents)}
                  events={office.events}
                  selected={selected}
                  onSelect={setSelected}
                />
              ) : (
                <div className="agent-list">
                  <div className="list-filters">
                    <select
                      aria-label="Filter department"
                      value={department}
                      onChange={(e) => setDepartment(e.target.value)}
                    >
                      <option value="all">All departments</option>
                      {[
                        "Executive",
                        "Research",
                        "Engineering",
                        "Review",
                        "Integrations",
                      ].map((d) => (
                        <option key={d} value={d.toLowerCase()}>
                          {d}
                        </option>
                      ))}
                    </select>
                    <span>{agents.length} agents</span>
                  </div>
                  {agents.map((agent) => {
                    const role = roleFor(agent);
                    return (
                      <button
                        className={`agent-row ${selected === agent.agent_id ? "selected" : ""}`}
                        key={agent.agent_id}
                        onClick={() => setSelected(agent.agent_id)}
                      >
                        <span
                          className="mini-portrait"
                          style={{ background: role.color }}
                        >
                          <Users size={15} />
                        </span>
                        <span>
                          <strong>{role.name}</strong>
                          <small>{agent.summary ?? role.title}</small>
                        </span>
                        <span className="list-department">
                          {role.department}
                        </span>
                        <Status status={agent.activity} />
                        <ArrowRight size={14} />
                      </button>
                    );
                  })}
                  {agents.length === 0 && (
                    <Empty
                      icon={<Search size={22} />}
                      text="No agents match your search."
                    />
                  )}
                </div>
              )}
            </div>
            <footer className="office-footer">
              <div>
                <span className="floor-marker">01</span>MAIN OFFICE
                <span className="footer-divider" />
                <span>Pixel space · Real activity</span>
              </div>
              <span>
                <Circle size={8} /> Select an agent to inspect
              </span>
            </footer>
          </section>
          <footer className="main-footer">
            <span>
              <Code2 size={13} /> SPOC HARNESS
            </span>
            <span>Durable work. Visible progress.</span>
          </footer>
        </main>
        <aside className="inspector" aria-label="Selected agent">
          {selectedAgent && (
            <Inspector
              key={`${officeVersion}:${selectedAgent.agent_id}`}
              agent={selectedAgent}
              events={office.events}
              artifacts={inspectedRun?.run_id === run?.run_id ? artifacts : []}
              run={inspectedRun}
              activityRunId={runId || undefined}
              snapshot={office.snapshot}
              onHistoryReset={onOfficeReset}
              subscribe={office.subscribe}
              busy={busy}
              onNote={async (content) => {
                if (!inspectedRun) return false;
                return perform(() =>
                  api.note(
                    inspectedRun.run_id,
                    content,
                    selectedAgent.agent_id,
                  ),
                );
              }}
            />
          )}
          {run?.report && (
            <button className="report-link" onClick={() => setModal("report")}>
              <CheckCheck size={17} />
              <span>Mission report is ready</span>
              <ArrowRight size={15} />
            </button>
          )}
        </aside>
      </div>
      {modal === "mission" && (
        <MissionModal
          settings={settings}
          onClose={() => setModal(null)}
          onSubmit={(input) => void create(input)}
          busy={busy}
          error={modalError}
        />
      )}{" "}
      {modal === "review" && reviewRun && (
        <ReviewModal
          run={reviewRun}
          artifacts={artifacts}
          events={office.events}
          onClose={() => setModal(null)}
          onSubmit={(input) =>
            void perform(() => api.resume(reviewRun.run_id, input), true)
          }
          busy={busy}
          error={modalError}
        />
      )}{" "}
      {modal === "settings" && (
        <Modal
          title="Workspace settings"
          subtitle="Choose how new missions run and manage this local harness."
          onClose={() => setModal(null)}
          wide
          className="settings-modal"
        >
          <WorkspaceSettings
            settings={settings}
            loading={settingsLoading}
            loadError={settingsError}
            initialSection={settingsSection}
            onSaved={setSettings}
            onRegenesis={regenesis}
            onReload={() => void reloadSettings()}
          />
        </Modal>
      )}{" "}
      {modal === "report" && run && (
        <Modal
          title="Mission report"
          subtitle={run.user_request}
          onClose={() => setModal(null)}
          wide
        >
          <div className="report-content">{run.report}</div>
        </Modal>
      )}
    </div>
  );
}
