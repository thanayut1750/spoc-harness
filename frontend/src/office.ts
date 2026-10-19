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
export interface OfficeRole extends Role {
  kind: "fixed" | "specialist" | "internal" | "external";
  parent_agent_id?: string;
  model_parent?: string;
}
export interface PositionedAgent {
  agent: AgentActivity;
  role: OfficeRole;
}
export const specialistsPerPage = 4;
export const integrationsPerPage = 3;
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
    id: "tools_rd_lead",
    name: "Tools R&D lead",
    title: "Tool research & development",
    department: "Engineering",
    color: "#c1b3e0",
    x: 805,
    y: 145,
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
export function agentMetadata(
  agent: AgentActivity,
  key: string,
): string | undefined {
  const value = agent.data?.[key];
  return typeof value === "string" && value.trim() ? value : undefined;
}
export function isEngineeringSpecialist(agent: AgentActivity): boolean {
  return (
    agent.source === "harness" &&
    agent.agent_id.startsWith("specialist:") &&
    agentMetadata(agent, "agent_type") === "engineering_specialist"
  );
}
export function isExternalAgent(agent: AgentActivity): boolean {
  return (
    (!!agent.source && agent.source !== "harness") ||
    (!agent.source && !roles.some((role) => role.id === agent.agent_id))
  );
}
export function roleFor(value: string | AgentActivity, index = 0): OfficeRole {
  const agent =
    typeof value === "string"
      ? { agent_id: value, activity: "idle" as const }
      : value;
  const id = agent.agent_id;
  const external = isExternalAgent(agent);
  const name =
    agent.display_name ?? agent.name ?? agentMetadata(agent, "display_name");
  const fixed = !external && roles.find((role) => role.id === id);
  if (fixed)
    return {
      ...fixed,
      name: name ?? fixed.name,
      kind: "fixed",
      parent_agent_id: agentMetadata(agent, "parent_agent_id"),
    };
  if (isEngineeringSpecialist(agent))
    return {
      id,
      name: name ?? "Engineering specialist",
      title: "Engineering specialist",
      department: "Engineering",
      color: "#a6c9e6",
      x: [640, 740, 840, 940][Math.max(0, index) % specialistsPerPage],
      y: 575,
      kind: "specialist",
      parent_agent_id:
        agentMetadata(agent, "parent_agent_id") ?? "engineering_head",
      model_parent:
        agentMetadata(agent, "model_parent") ??
        agentMetadata(agent, "base_role"),
    };
  if (!external)
    return {
      id,
      name: name ?? pretty(id),
      title:
        id === "triage_router"
          ? "Workflow routing · TypeSafe Jev"
          : "Internal coordinator",
      department: "Executive",
      color: "#d9bbf3",
      x: 500,
      y: 225,
      kind: "internal",
    };
  return {
    id,
    name:
      name ?? pretty(id.includes(":") ? id.split(":").slice(1).join(":") : id),
    title: "Connected agent",
    department: "Integrations",
    color: "#d2bca4",
    x: [85, 225, 365][Math.max(0, index) % integrationsPerPage],
    y: 575,
    kind: "external",
  };
}
export function officeRoster(
  agents: AgentActivity[],
  specialistPage = 0,
  integrationPage = 0,
) {
  const ordered = [...agents].sort((a, b) =>
    a.agent_id.localeCompare(b.agent_id),
  );
  const specialists = ordered.filter(isEngineeringSpecialist);
  const integrations = ordered.filter(isExternalAgent);
  const specialistPages = Math.max(
    1,
    Math.ceil(specialists.length / specialistsPerPage),
  );
  const integrationPages = Math.max(
    1,
    Math.ceil(integrations.length / integrationsPerPage),
  );
  const currentSpecialistPage = Math.max(
    0,
    Math.min(specialistPage, specialistPages - 1),
  );
  const currentIntegrationPage = Math.max(
    0,
    Math.min(integrationPage, integrationPages - 1),
  );
  const positioned: PositionedAgent[] = [
    ...agents
      .filter(
        (agent) => !isExternalAgent(agent) && !isEngineeringSpecialist(agent),
      )
      .map((agent) => ({ agent, role: roleFor(agent) })),
    ...specialists
      .slice(
        currentSpecialistPage * specialistsPerPage,
        (currentSpecialistPage + 1) * specialistsPerPage,
      )
      .map((agent, index) => ({ agent, role: roleFor(agent, index) })),
    ...integrations
      .slice(
        currentIntegrationPage * integrationsPerPage,
        (currentIntegrationPage + 1) * integrationsPerPage,
      )
      .map((agent, index) => ({ agent, role: roleFor(agent, index) })),
  ];
  return {
    positioned,
    specialists,
    integrations,
    specialistPages,
    integrationPages,
    specialistPage: currentSpecialistPage,
    integrationPage: currentIntegrationPage,
  };
}
export function handoffEndpoints(
  event: ActivityEvent,
  positioned: PositionedAgent[],
) {
  const raw = event.data?.target_agent_id ?? event.data?.to_agent_id;
  if (typeof raw !== "string") return undefined;
  const target =
    event.source &&
    event.source !== "harness" &&
    !raw.startsWith(`${event.source}:`)
      ? `${event.source}:${raw}`
      : raw;
  const from = positioned.find(
    ({ agent }) => agent.agent_id === event.agent_id,
  )?.role;
  const to = positioned.find(({ agent }) => agent.agent_id === target)?.role;
  return from && to ? { from, to } : undefined;
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
  const retainedIdentity =
    current?.source === "harness" &&
    event.source === "harness" &&
    current.run_id === event.run_id
      ? Object.fromEntries(
          [
            "agent_type",
            "display_name",
            "parent_agent_id",
            "department",
            "model_parent",
            "base_role",
          ].flatMap((key) =>
            current.data?.[key] === undefined ? [] : [[key, current.data[key]]],
          ),
        )
      : {};
  return {
    ...agents,
    [event.agent_id]: {
      ...current,
      ...event,
      data: { ...retainedIdentity, ...event.data },
    },
  };
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
