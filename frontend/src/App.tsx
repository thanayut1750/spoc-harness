import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity as ActivityIcon,
  ArrowDownToLine,
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
  Radio,
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
import { OfficeCanvas } from "./OfficeCanvas";
import {
  activeActivities,
  activityLabels,
  pretty,
  progressStatus,
  roleFor,
} from "./office";
import { useOffice } from "./useOffice";
import type {
  ActivityEvent,
  AgentActivity,
  Artifact,
  ResumeInput,
  ReviewAction,
  Run,
  RunInput,
} from "./types";

const terminalStatuses = new Set([
  "completed",
  "succeeded",
  "success",
  "failed",
  "cancelled",
  "aborted",
]);
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
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className={`modal ${wide ? "modal-wide" : ""}`}
      onClose={onClose}
      onClick={(event) => {
        if (event.target === dialog.current) onClose();
      }}
    >
      <div className="modal-heading">
        <div>
          <span className="eyebrow">SPOC WORKSPACE</span>
          <h2>{title}</h2>
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
  onClose,
  onSubmit,
  busy,
  error,
}: {
  onClose: () => void;
  onSubmit: (input: RunInput) => void;
  busy: boolean;
  error: string;
}) {
  const [request, setRequest] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [mission, setMission] = useState("");
  const [prohibited, setProhibited] = useState("");
  const [rules, setRules] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({
      user_request: request.trim(),
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
            disabled={busy || request.trim().length < 3}
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
  onClose,
  onSubmit,
  busy,
  error,
}: {
  run: Run;
  onClose: () => void;
  onSubmit: (input: ResumeInput) => void;
  busy: boolean;
  error: string;
}) {
  const [action, setAction] = useState<ReviewAction>(
    run.review?.kind === "manual_pause" ? "continue" : "provide_context",
  );
  const [context, setContext] = useState("");
  const [kr, setKr] = useState(run.review?.kr_id ?? "");
  const [description, setDescription] = useState("");
  const [criteria, setCriteria] = useState("");
  const results = run.objectives?.flatMap((o) => o.key_results) ?? [];
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!run.review) return;
    onSubmit({
      interrupt_id: run.review.interrupt_id,
      action,
      ...(context.trim() ? { context: context.trim() } : {}),
      ...(action === "revise_kr"
        ? {
            kr_id: kr,
            description: description.trim(),
            acceptance_criteria: criteria
              .split("\n")
              .map((c) => c.trim())
              .filter(Boolean),
          }
        : {}),
    });
  }
  return (
    <Modal
      title="The office needs your direction"
      subtitle="Your decision resumes the saved workflow at its review boundary."
      onClose={onClose}
    >
      <div className="review-context">
        <ShieldCheck size={20} />
        <div>
          <span className="eyebrow">
            {pretty(run.review?.kind ?? "Review")}
          </span>
          <p>
            {run.review?.message ??
              "Waiting for the worker to reach its pause boundary."}
          </p>
        </div>
      </div>
      <form onSubmit={submit}>
        <label>
          Decision
          <select
            value={action}
            onChange={(e) => setAction(e.target.value as ReviewAction)}
          >
            <option value="provide_context">Provide context and retry</option>
            <option value="revise_kr">Revise a key result</option>
            <option value="retry_operation">
              Retry the reviewed operation
            </option>
            <option value="continue">Continue execution</option>
            <option value="abort">Abort this run</option>
          </select>
        </label>
        {action === "revise_kr" && (
          <>
            <label>
              Key result
              <select
                required
                value={kr}
                onChange={(e) => {
                  setKr(e.target.value);
                  const result = results.find(
                    (r) => r.kr_id === e.target.value,
                  );
                  setDescription(result?.description ?? "");
                  setCriteria(result?.acceptance_criteria.join("\n") ?? "");
                }}
              >
                <option value="">Select a key result</option>
                {results.map((r) => (
                  <option key={r.kr_id} value={r.kr_id}>
                    {r.kr_id}: {r.description}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Revised description
              <textarea
                required
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label>
              Acceptance criteria, one per line
              <textarea
                required
                rows={3}
                value={criteria}
                onChange={(e) => setCriteria(e.target.value)}
              />
            </label>
            <small>
              A revision creates a new KR version and invalidates dependent
              approvals.
            </small>
          </>
        )}
        <label>
          {action === "abort" ? "Reason" : "Context for the team"}
          <textarea
            rows={4}
            value={context}
            onChange={(e) => setContext(e.target.value)}
            required={action === "provide_context"}
            placeholder="Explain the decision or add the missing information…"
          />
        </label>
        {action === "retry_operation" && (
          <p className="form-help">
            The prior operation may have completed before interruption. Review
            its output before requesting another execution.
          </p>
        )}
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="modal-footer">
          <button type="button" className="text-button" onClick={onClose}>
            Decide later
          </button>
          <button
            className={action === "abort" ? "danger-button" : "primary-button"}
            disabled={busy || !run.review}
          >
            {busy ? (
              <LoaderCircle size={16} className="spin" />
            ) : (
              <Play size={15} />
            )}{" "}
            Apply decision
          </button>
        </div>
      </form>
    </Modal>
  );
}
function IntegrationsModal({ onClose }: { onClose: () => void }) {
  return (
    <Modal
      title="Bring another agent to the office"
      subtitle="Project activity from your own tools into the connected workspace."
      onClose={onClose}
    >
      <div className="integration-endpoint">
        <span>POST</span>
        <code>/api/integrations/events</code>
      </div>
      <p className="form-help">
        Send a source-scoped event ID for deduplication. External events update
        a character’s activity; they cannot control internal runs or approve
        work.
      </p>
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
        Activities: idle, planning, reading, writing, executing, reviewing,
        waiting, completed, error. Credentials stay server-side.
      </p>
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
        Two departments · Two concurrent work packages
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
}: {
  agent: AgentActivity;
  events: ActivityEvent[];
  artifacts: Artifact[];
  run: Run | null;
  onNote: (content: string) => Promise<boolean>;
  busy: boolean;
}) {
  const [tab, setTab] = useState("overview");
  const [note, setNote] = useState("");
  const [sent, setSent] = useState(false);
  const role = roleFor(agent.agent_id);
  const relevant = events.filter((e) => e.agent_id === agent.agent_id);
  const outcome = agent.kr_id ? run?.outcomes?.[agent.kr_id] : undefined;
  const canGuide =
    !!run &&
    !terminalStatuses.has(run.status) &&
    (!agent.source || agent.source === "harness");
  const files = artifacts.filter(
    (a) => !agent.kr_id || !a.kr_id || a.kr_id === agent.kr_id,
  );
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
        <h2>{agent.display_name ?? agent.name ?? role.name}</h2>
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
            {relevant.length === 0 ? (
              <Empty
                icon={<ActivityIcon size={21} />}
                text="No activity recorded for this agent yet."
              />
            ) : (
              relevant.map((event) => (
                <div key={event.seq}>
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
          </div>
        ) : (
          <div className="artifact-list">
            {files.length === 0 ? (
              <Empty
                icon={<FileText size={22} />}
                text="Artifacts and evidence will be collected here."
              />
            ) : (
              files.map((file) => (
                <a
                  key={file.artifact_id}
                  href={`/api/artifacts/${encodeURIComponent(file.artifact_id)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <FileText size={18} />
                  <div>
                    <strong>{file.name}</strong>
                    <span>
                      {file.media_type}
                      {typeof file.size === "number"
                        ? ` · ${(file.size / 1024).toFixed(1)} KB`
                        : ""}
                    </span>
                  </div>
                  <ArrowDownToLine size={15} />
                </a>
              ))
            )}
          </div>
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
            : agent.source && agent.source !== "harness"
              ? "External activity is read-only."
              : "Delivered at the next applicable work boundary."}
        </small>
      </form>
    </>
  );
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
    "mission" | "review" | "integrations" | "report" | null
  >(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [modalError, setModalError] = useState("");
  const [filter, setFilter] = useState("");
  const [department, setDepartment] = useState("all");
  const selectedRun = useRef(runId);
  useEffect(() => {
    selectedRun.current = runId;
  }, [runId]);
  const refreshRuns = useCallback(async () => {
    try {
      const items = await api.runs();
      setRuns(items);
      setRunId((current) => current || items[0]?.run_id || "");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Cannot load runs");
    }
  }, []);
  const refreshDetail = useCallback(async (id: string) => {
    try {
      const [detail, files] = await Promise.all([
        api.run(id),
        api.artifacts(id),
      ]);
      if (selectedRun.current === id) {
        setRun(detail);
        setArtifacts(files);
      }
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Cannot load mission",
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
  const office = useOffice(onEvent);
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
    if (!runId) return;
    void refreshDetail(runId);
    const timer = setInterval(() => void refreshDetail(runId), 5000);
    return () => clearInterval(timer);
  }, [runId, refreshDetail]);
  const allAgents = Object.values(office.agents);
  const agents = allAgents.filter(
    (agent) =>
      (department === "all" ||
        roleFor(agent.agent_id).department.toLowerCase() === department) &&
      (!filter ||
        (agent.display_name ?? roleFor(agent.agent_id).name)
          .toLowerCase()
          .includes(filter.toLowerCase())),
  );
  const active = allAgents.filter((agent) =>
    activeActivities.has(agent.activity),
  ).length;
  const selectedAgent = office.agents[selected] ?? allAgents[0];
  const events = office.events.filter(
    (event) => !runId || event.run_id === runId || !event.run_id,
  );
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
            aria-label="Integration settings"
            onClick={() => setModal("integrations")}
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
            onClick={() => setModal("integrations")}
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
          <details className="mobile-strategy">
            <summary>
              <Layers3 size={14} /> Strategic pyramid <ChevronDown size={13} />
            </summary>
            <Pyramid run={run} />
          </details>
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={14} />
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
                <strong>Your direction is needed</strong>
                <span>{reviewRun?.review?.message}</span>
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
                    const role = roleFor(agent.agent_id);
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
                          <strong>{agent.display_name ?? role.name}</strong>
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
          <section className="activity-section">
            <div className="activity-heading">
              <h2>
                <ActivityIcon size={16} /> Activity stream{" "}
                <span className="tiny-count">{events.length}</span>
              </h2>
              <span className="live-word">
                <Radio size={12} />{" "}
                {office.connection === "live" ? "LIVE" : "AWAITING CONNECTION"}
              </span>
            </div>
            {events.length === 0 ? (
              <div className="timeline-empty">
                <span className="timeline-line" />
                <div>
                  <span className="small-dot" />
                  <strong>The office is ready</strong>
                  <p>
                    {run
                      ? "Activity will appear here as the organization works."
                      : "Create a mission to see your organization get to work."}
                  </p>
                </div>
              </div>
            ) : (
              <div className="timeline">
                {events.slice(0, 60).map((event) => (
                  <button
                    key={event.seq}
                    onClick={() => setSelected(event.agent_id)}
                  >
                    <Stamp date={event.timestamp} />
                    <span className={`small-dot ${event.activity}`} />
                    <strong>
                      {event.display_name ?? roleFor(event.agent_id).name}
                    </strong>
                    <span>
                      {event.summary ?? activityLabels[event.activity]}
                    </span>
                    <code>{event.kr_id ?? ""}</code>
                  </button>
                ))}
              </div>
            )}
          </section>
          {run?.report && (
            <button className="report-link" onClick={() => setModal("report")}>
              <CheckCheck size={17} />
              <span>Mission report is ready</span>
              <ArrowRight size={15} />
            </button>
          )}
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
              key={selectedAgent.agent_id}
              agent={selectedAgent}
              events={office.events}
              artifacts={artifacts}
              run={run}
              busy={busy}
              onNote={async (content) => {
                if (!run) return false;
                return perform(() =>
                  api.note(run.run_id, content, selectedAgent.agent_id),
                );
              }}
            />
          )}
        </aside>
      </div>
      {modal === "mission" && (
        <MissionModal
          onClose={() => setModal(null)}
          onSubmit={(input) => void create(input)}
          busy={busy}
          error={modalError}
        />
      )}{" "}
      {modal === "review" && reviewRun && (
        <ReviewModal
          run={reviewRun}
          onClose={() => setModal(null)}
          onSubmit={(input) =>
            void perform(() => api.resume(reviewRun.run_id, input), true)
          }
          busy={busy}
          error={modalError}
        />
      )}{" "}
      {modal === "integrations" && (
        <IntegrationsModal onClose={() => setModal(null)} />
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
