import { describe, expect, it } from "vitest";
import {
  appendEvent,
  activeActivities,
  displayActivity,
  initialAgents,
  normalizeAgent,
  parseActivityEvent,
  projectEvent,
  routingSummary,
  roleFor,
  officeRoster,
  handoffEndpoints,
} from "./office";
import type { ActivityEvent } from "./types";
const event = (
  seq = 1,
  extras: Partial<ActivityEvent> = {},
): ActivityEvent => ({
  event_id: `event-${seq}`,
  seq,
  source: "harness",
  agent_id: "backend_coder",
  activity: "executing",
  summary: "Running tests",
  timestamp: "2026-10-18T10:00:00Z",
  ...extras,
});
describe("office projection", () => {
  it("starts each internal role idle and projects only supplied facts", () => {
    const agents = initialAgents();
    expect(Object.keys(agents)).toHaveLength(11);
    expect(Object.values(agents).every((a) => a.activity === "idle")).toBe(
      true,
    );
    const next = projectEvent(agents, event());
    expect(next.backend_coder.activity).toBe("executing");
    expect(next.market_researcher.activity).toBe("idle");
    expect(agents.backend_coder.activity).toBe("idle");
  });
  it("keeps external agents separate from identically named internal roles", () => {
    const incoming = normalizeAgent(event(2, { source: "custom-office" }));
    const next = projectEvent(initialAgents(), incoming);
    expect(next.backend_coder.activity).toBe("idle");
    expect(next["custom-office:backend_coder"].activity).toBe("executing");
    expect(incoming.original_agent_id).toBe("backend_coder");
  });
  it("does not regress a newer activity with a stale event", () => {
    const current = projectEvent(initialAgents(), event(2));
    expect(
      projectEvent(
        current,
        event(2, { activity: "idle", timestamp: "2026-10-18T09:59:00Z" }),
      ),
    ).toBe(current);
  });
  it("stops terminal run activity without changing its recorded evidence", () => {
    const recorded = event(3, {
      run_id: "finished-run",
      data: { stdout: "Acceptance tests passed" },
    });
    const displayed = displayActivity(recorded, { status: "succeeded" });
    expect(displayed.activity).toBe("completed");
    expect(activeActivities.has(displayed.activity)).toBe(false);
    expect(displayed.summary).toContain("Run succeeded.");
    expect(displayed.summary).toContain("Executing — Running tests");
    expect(displayed.data).toBe(recorded.data);
    expect(displayed.run_id).toBe("finished-run");
    expect(recorded.activity).toBe("executing");
    expect(recorded.summary).toBe("Running tests");
  });
  it("shows failure, cancellation, and paused work as inactive", () => {
    expect(displayActivity(event(), { status: "failed" }).activity).toBe(
      "error",
    );
    expect(displayActivity(event(), { status: "cancelled" }).activity).toBe(
      "idle",
    );
    for (const status of ["paused", "review", "queued"]) {
      expect(displayActivity(event(), { status }).activity).toBe("waiting");
    }
    expect(displayActivity(event(), undefined).activity).toBe("waiting");
    const running = event();
    expect(displayActivity(running, { status: "running" })).toBe(running);
  });
  it("keeps external webhook activity independent of harness run status", () => {
    const external = normalizeAgent(event(4, { source: "custom-office" }));
    expect(displayActivity(external, { status: "succeeded" })).toBe(external);
    expect(displayActivity(external, undefined)).toBe(external);
  });
  it("describes only the departments and team selected by triage", () => {
    const triage = { departments: ["engineering"], reason: "Local code fix" };
    expect(routingSummary({ ...triage, mode: "FAST_TRACK" })).toBe(
      "Engineering only · One worker",
    );
    expect(routingSummary({ ...triage, mode: "DEPARTMENTAL" })).toBe(
      "Engineering only · Department team",
    );
    expect(
      routingSummary({
        ...triage,
        departments: ["research", "engineering"],
        mode: "FULL_PYRAMID",
      }),
    ).toBe("Research + Engineering · Full Pyramid");
    expect(routingSummary(undefined)).toBe(
      "Routing is chosen for each mission",
    );
  });
  it("deduplicates deliveries and retains a bounded sequence-ordered timeline", () => {
    let events: ActivityEvent[] = [];
    for (let n = 0; n < 230; n++) events = appendEvent(events, event(n));
    expect(events).toHaveLength(200);
    expect(events[0].seq).toBe(229);
    expect(appendEvent(events, event(229))).toBe(events);
    expect(appendEvent(events, event(300, { event_id: "event-229" }))).toBe(
      events,
    );
  });
  it("retains independent sources that reuse an event ID", () => {
    const first = event(1, { event_id: "shared", source: "first" });
    const second = event(2, { event_id: "shared", source: "second" });
    expect(appendEvent([first], second)).toHaveLength(2);
  });
  it("ignores malformed or unsupported activity messages", () => {
    expect(parseActivityEvent("not json")).toBeNull();
    expect(
      parseActivityEvent(
        JSON.stringify(
          event(1, { activity: "fake" as ActivityEvent["activity"] }),
        ),
      ),
    ).toBeNull();
    expect(parseActivityEvent(JSON.stringify(event()))?.seq).toBe(1);
  });
  it("recognizes named Engineering specialists only from internal metadata and retains their identity", () => {
    const specialist = event(4, {
      agent_id: "specialist:run:1234567890abcdef",
      data: {
        agent_type: "engineering_specialist",
        display_name: "Shader specialist",
        parent_agent_id: "engineering_head",
        model_parent: "backend_coder",
        department: "engineering",
        stdout: "Previous tool output",
      },
    });
    expect(roleFor(specialist)).toMatchObject({
      name: "Shader specialist",
      kind: "specialist",
      department: "Engineering",
      parent_agent_id: "engineering_head",
      model_parent: "backend_coder",
    });
    const external = normalizeAgent({ ...specialist, source: "custom-office" });
    expect(roleFor(external)).toMatchObject({
      name: "Shader specialist",
      kind: "external",
      department: "Integrations",
    });
    const updated = projectEvent(projectEvent(initialAgents(), specialist), {
      ...specialist,
      seq: 5,
      data: { tool_name: "compile" },
      activity: "reading",
    });
    expect(roleFor(updated[specialist.agent_id]).name).toBe(
      "Shader specialist",
    );
    expect(roleFor(updated[specialist.agent_id]).kind).toBe("specialist");
    expect(updated[specialist.agent_id].data?.stdout).toBeUndefined();
    expect(
      officeRoster([{ ...specialist, agent_id: "backend_coder" }]).specialists,
    ).toHaveLength(0);
    expect(roleFor({ ...specialist, source: undefined }).kind).toBe("external");
  });
  it("pages all bounded specialists without overlapping Integration desks and resolves actual handoff positions", () => {
    const specialists = Array.from({ length: 36 }, (_, index) =>
      event(index + 10, {
        agent_id: `specialist:run:${String(index).padStart(16, "0")}`,
        data: {
          agent_type: "engineering_specialist",
          display_name: `Specialist ${index}`,
          parent_agent_id: "engineering_head",
        },
      }),
    );
    const integration = normalizeAgent(event(60, { source: "external" }));
    const agents = [
      ...Object.values(initialAgents()),
      ...specialists,
      integration,
    ];
    const visited = new Set<string>();
    for (let page = 0; page < officeRoster(agents).specialistPages; page++) {
      const roster = officeRoster(agents, page);
      const desks = roster.positioned.filter(
        ({ role }) => role.kind === "specialist",
      );
      expect(desks).toHaveLength(4);
      const coordinates = roster.positioned.map(
        ({ role }) => `${role.x}:${role.y}`,
      );
      expect(new Set(coordinates).size).toBe(coordinates.length);
      for (const { agent, role } of desks) {
        visited.add(agent.agent_id);
        expect(role.department).toBe("Engineering");
        expect(role.x).toBeGreaterThan(600);
        expect(role.y).toBeLessThan(650);
      }
      const target = desks[3];
      expect(
        handoffEndpoints(
          event(100, {
            agent_id: "engineering_head",
            data: { target_agent_id: target.agent.agent_id },
          }),
          roster.positioned,
        )?.to,
      ).toBe(target.role);
    }
    expect(visited.size).toBe(36);
    const first = officeRoster(agents).positioned;
    expect(
      handoffEndpoints(
        event(101, {
          agent_id: integration.agent_id,
          source: "external",
          data: { target_agent_id: "engineering_head" },
        }),
        first,
      ),
    ).toBeUndefined();
    expect(roleFor("tools_rd_lead")).toMatchObject({
      name: "Tools R&D lead",
      kind: "fixed",
      department: "Engineering",
    });
  });
});
