import type { Activity, ActivityEvent, AgentActivity, Run } from "./types";
export interface Role {
  id: string;
  name: string;
  title: string;
  department: string;
  color: string;
  x: number;
  y: number;
}
export const roles: Role[] = [
  {
    id: "planner",
    name: "Planner",
    title: "Strategy & decomposition",
    department: "Executive",
    color: "#d9bbf3",
    x: 420,
    y: 126,
  },
  {
    id: "executive",
    name: "Executive",
    title: "Organization supervisor",
    department: "Executive",
    color: "#d9bbf3",
    x: 580,
    y: 126,
  },
  {
    id: "research_head",
    name: "Research lead",
    title: "Department head",
    department: "Research",
    color: "#a9d5ad",
    x: 204,
    y: 300,
  },
  {
    id: "market_researcher",
    name: "Market researcher",
    title: "Research specialist",
    department: "Research",
    color: "#a9d5ad",
    x: 138,
    y: 420,
  },
  {
    id: "data_analyst",
    name: "Data analyst",
    title: "Research specialist",
    department: "Research",
    color: "#a9d5ad",
    x: 288,
    y: 420,
  },
  {
    id: "engineering_head",
    name: "Engineering lead",
    title: "Department head",
    department: "Engineering",
    color: "#a6c9e6",
    x: 796,
    y: 300,
  },
  {
    id: "system_architect",
    name: "System architect",
    title: "Engineering specialist",
    department: "Engineering",
    color: "#a6c9e6",
    x: 712,
    y: 420,
  },
  {
    id: "backend_coder",
    name: "Backend coder",
    title: "Engineering specialist",
    department: "Engineering",
    color: "#a6c9e6",
    x: 862,
    y: 420,
  },
  {
    id: "research_gatekeeper",
    name: "Research reviewer",
    title: "Quality gatekeeper",
    department: "Review",
    color: "#e7c88c",
    x: 450,
    y: 352,
  },
  {
    id: "engineering_gatekeeper",
    name: "Engineering reviewer",
    title: "Quality gatekeeper",
    department: "Review",
    color: "#e7c88c",
    x: 550,
    y: 352,
  },
];
export const activityLabels: Record<Activity, string> = {
  idle: "Idle",
  planning: "Planning",
  reading: "Reading",
  writing: "Writing",
  executing: "Executing",
  reviewing: "Reviewing",
  waiting: "Waiting",
  completed: "Completed",
  error: "Needs attention",
};
export const activeActivities = new Set<Activity>([
  "planning",
  "reading",
  "writing",
  "executing",
  "reviewing",
]);
export const terminalStatuses = new Set([
  "completed",
  "succeeded",
  "success",
  "failed",
  "cancelled",
  "aborted",
]);
export function displayActivity(
  agent: AgentActivity,
  run: Pick<Run, "status"> | undefined,
): AgentActivity {
  if (
    (agent.source && agent.source !== "harness") ||
    !activeActivities.has(agent.activity) ||
    run?.status === "running"
  )
    return agent;
  const activity: Activity = !run
    ? "waiting"
    : run.status === "failed"
      ? "error"
      : ["completed", "succeeded", "success"].includes(run.status)
        ? "completed"
        : ["cancelled", "aborted"].includes(run.status)
          ? "idle"
          : "waiting";
  const status = run
    ? `Run ${run.status.replaceAll("_", " ")}.`
    : "Waiting for the run’s current status.";
  return {
    ...agent,
    activity,
    summary: `${status} Last recorded activity: ${activityLabels[agent.activity]}${agent.summary ? ` — ${agent.summary}` : "."}`,
  };
}
export function routingSummary(triage: Run["triage"]): string {
  if (!triage) return "Routing is chosen for each mission";
  const departments = [...new Set(triage.departments)].map(pretty).join(" + ");
  const team = departments || "No departments assigned";
  if (triage.mode === "FAST_TRACK") return `${team} only · One worker`;
  if (triage.mode === "DEPARTMENTAL") return `${team} only · Department team`;
  return `${team} · ${pretty(triage.mode.toLowerCase())}`;
}
export function pretty(value: string): string {
  return value.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
export function roleFor(id: string, index = 0): Role {
  return (
    roles.find((role) => role.id === id) ?? {
      id,
      name: pretty(id.includes(":") ? id.split(":").slice(1).join(":") : id),
      title: "Connected agent",
      department: "Integrations",
      color: "#d2bca4",
      x: [85, 225, 365, 635, 775, 915][Math.max(0, index) % 6],
      y: 575,
    }
  );
}
export function normalizeAgent<T extends AgentActivity>(agent: T): T {
  if (!agent.source || agent.source === "harness") return agent;
  return {
    ...agent,
    original_agent_id: agent.agent_id,
    agent_id: `${agent.source}:${agent.agent_id}`,
  };
}
export function initialAgents(): Record<string, AgentActivity> {
  return Object.fromEntries(
    roles.map((role) => [
      role.id,
      { agent_id: role.id, activity: "idle" as const },
    ]),
  );
}
export function projectEvent(
  agents: Record<string, AgentActivity>,
  event: ActivityEvent,
): Record<string, AgentActivity> {
  if (!event.agent_id) return agents;
  const current = agents[event.agent_id];
  if (current?.seq !== undefined && current.seq >= event.seq) return agents;
  return { ...agents, [event.agent_id]: { ...current, ...event } };
}
export function appendEvent(
  events: ActivityEvent[],
  event: ActivityEvent,
): ActivityEvent[] {
  if (
    events.some(
      (item) =>
        (item.source === event.source && item.event_id === event.event_id) ||
        item.seq === event.seq,
    )
  )
    return events;
  return [event, ...events].sort((a, b) => b.seq - a.seq).slice(0, 200);
}
export function progressStatus(
  value: string | { status: string } | undefined,
): string {
  return typeof value === "string" ? value : (value?.status ?? "pending");
}
export function parseActivityEvent(data: string): ActivityEvent | null {
  try {
    const event = JSON.parse(data) as ActivityEvent;
    if (
      typeof event.seq !== "number" ||
      typeof event.event_id !== "string" ||
      typeof event.agent_id !== "string" ||
      !Object.hasOwn(activityLabels, event.activity) ||
      typeof event.timestamp !== "string"
    )
      return null;
    return event;
  } catch {
    return null;
  }
}
