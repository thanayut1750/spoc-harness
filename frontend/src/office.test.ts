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
  latestAgentActivities,
  agentIdentityKey,
  followRosterPage,
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
    expect(
      next[agentIdentityKey("custom-office", "backend_coder")].activity,
    ).toBe("executing");
    expect(incoming.original_agent_id).toBe("backend_coder");
  });
  it("isolates delimiter collisions, dynamic internal IDs, and encoded-looking raw IDs", () => {
    const internal = event(1, {
      agent_id: "specialist:run:1234567890abcdef",
      data: {
        agent_type: "engineering_specialist",
        display_name: "Shader specialist",
      },
    });
    const incoming = [
      internal,
      normalizeAgent(
        event(2, { source: "specialist", agent_id: "run:1234567890abcdef" }),
      ),
      normalizeAgent(event(3, { source: "a", agent_id: "b:c" })),
      normalizeAgent(event(4, { source: "a:b", agent_id: "c" })),
      normalizeAgent(
        event(5, { source: "a", agent_id: 'external:["a","b:c"]' }),
      ),
      normalizeAgent(
        event(6, { source: "ทีม😀", agent_id: 'quoted:"\\:วิศวกร' }),
      ),
    ];
    const projected = incoming.reduce(projectEvent, initialAgents());
    expect(new Set(incoming.map((agent) => agent.agent_id)).size).toBe(
      incoming.length,
    );
    for (const agent of incoming)
      expect(projected[agent.agent_id].seq).toBe(agent.seq);
    expect(roleFor(projected[internal.agent_id]).kind).toBe("specialist");
    for (const agent of incoming.slice(1)) {
      expect(roleFor(projected[agent.agent_id]).kind).toBe("external");
      expect(normalizeAgent(agent)).toEqual(agent);
    }
    expect(roleFor(normalizeAgent(event(7, { source: "custom" }))).name).toBe(
      "Backend Coder",
    );
  });
  it("keeps the newest duplicate snapshot regardless of legacy row order", () => {
    const older = normalizeAgent(
      event(1, { source: "custom", summary: "Old activity" }),
    );
    const newer = normalizeAgent(
      event(2, { source: "custom", summary: "Current activity" }),
    );
    for (const rows of [
      [older, newer],
      [newer, older],
    ]) {
      const projected = latestAgentActivities(rows);
      expect(Object.values(projected)).toEqual([newer]);
      expect(projectEvent(projected, older)).toBe(projected);
    }
  });
  it("replaces omitted mission, KR and display fields rather than leaking the preceding event", () => {
    const previous = event(1, {
      run_id: "prior-run",
      kr_id: "prior-kr",
      summary: "Old action",
      display_name: "Old name",
      name: "Old alias",
      department: "Old department",
      data: { stdout: "Previous proof" },
    });
    const bare: ActivityEvent = {
      seq: 2,
      event_id: "bare",
      source: "harness",
      agent_id: previous.agent_id,
      activity: "completed",
      timestamp: previous.timestamp,
    };
    const projected = projectEvent(
      projectEvent(initialAgents(), previous),
      bare,
    )[bare.agent_id];
    expect(projected).toEqual({ ...bare, data: {} });
    const sameRun = projectEvent(projectEvent(initialAgents(), previous), {
      ...bare,
      run_id: "prior-run",
    })[bare.agent_id];
    expect(sameRun.run_id).toBe("prior-run");
    expect(sameRun.kr_id).toBeUndefined();
    const external = normalizeAgent({ ...previous, source: "feed" });
    const externalBare = normalizeAgent({ ...bare, source: "feed" });
    const externalNext = projectEvent(
      projectEvent(initialAgents(), external),
      externalBare,
    )[externalBare.agent_id];
    expect(externalNext.run_id).toBeUndefined();
    expect(externalNext.summary).toBeUndefined();
  });
  it("retains only same-run internal specialist identity, including its public name", () => {
    const activated = event(1, {
      agent_id: "specialist:run:1234567890abcdef",
      run_id: "run",
      display_name: "Shader specialist",
      name: "Old alias",
      kr_id: "old-kr",
      data: {
        agent_type: "engineering_specialist",
        display_name: "Shader specialist",
        model_parent: "backend_coder",
        stdout: "Old output",
      },
    });
    const bare = event(2, {
      agent_id: activated.agent_id,
      run_id: "run",
      data: {},
    });
    const current = projectEvent(initialAgents(), activated);
    const next = projectEvent(current, bare)[bare.agent_id];
    expect(next.display_name).toBe("Shader specialist");
    expect(next.data).toEqual({
      agent_type: "engineering_specialist",
      display_name: "Shader specialist",
      model_parent: "backend_coder",
    });
    expect(next.kr_id).toBeUndefined();
    expect(next.name).toBeUndefined();
    for (const run_id of [undefined, "another-run"])
      expect(projectEvent(current, { ...bare, run_id })[bare.agent_id]).toEqual(
        { ...bare, run_id, data: {} },
      );
  });
  it("resolves raw and normalized handoff targets only inside their exact source", () => {
    const sender = normalizeAgent(
      event(1, { source: "a", agent_id: "sender" }),
    );
    const rawPrefix = normalizeAgent(
      event(2, { source: "a", agent_id: "a:target" }),
    );
    const target = normalizeAgent(
      event(3, { source: "a", agent_id: "target" }),
    );
    const encodedRaw = normalizeAgent(
      event(4, { source: "a", agent_id: target.agent_id }),
    );
    const foreign = normalizeAgent(
      event(5, { source: "other", agent_id: "target" }),
    );
    const agents = [sender, rawPrefix, target, encodedRaw, foreign];
    const positioned = officeRoster(agents).positioned;
    // The paged roster has only three integrations, so use explicit positions for all endpoints.
    const all = agents.map((agent, index) => ({
      agent,
      role: roleFor(agent, index),
    }));
    expect(positioned.length).toBeGreaterThan(0);
    const handoff = (raw: string) =>
      handoffEndpoints({ ...sender, data: { target_agent_id: raw } }, all)?.to;
    expect(handoff("a:target")).toBe(all[1].role);
    expect(handoff(target.agent_id)).toBe(all[3].role); // exact raw ID wins
    expect(
      handoffEndpoints(
        { ...sender, data: { to_agent_id: target.agent_id } },
        all.filter(({ agent }) => agent !== encodedRaw),
      )?.to,
    ).toBe(all[2].role);
    expect(handoff(foreign.agent_id)).toBeUndefined();
    expect(handoff("backend_coder")).toBeUndefined();
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
      run_id: "run",
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

describe.each([
  ["Engineering specialists", 4],
  ["external integrations", 3],
] as const)("%s desk-page following", (_group, perPage) => {
  const members = () =>
    Array.from({ length: perPage + 1 }, (_, index) =>
      event(index + 1, {
        agent_id: `agent-${index}`,
        activity: "completed",
      }),
    );
  it("initially follows working agents before newer completed agents, then the newest non-error snapshot", () => {
    const agents = members();
    const selected = "executive";
    expect(followRosterPage({ agents, page: 0, perPage, selected })).toBe(1);
    expect(
      followRosterPage({
        agents: [{ ...agents[0], activity: "reading" }, ...agents.slice(1)],
        page: 1,
        perPage,
        selected,
      }),
    ).toBe(0);
  });
  it("follows a new identity even when its first event is completed and an older agent stays selected", () => {
    const agents = members();
    const selected = agents[0].agent_id;
    const previous = {
      ids: agents.slice(0, perPage).map((agent) => agent.agent_id),
      selected,
    };
    expect(
      followRosterPage({ agents, page: 0, perPage, selected, previous }),
    ).toBe(1);
    expect(
      followRosterPage({
        agents,
        page: 0,
        perPage,
        selected,
        previous: { ids: [], selected },
      }),
    ).toBe(1);
  });
  it("preserves manual Previous and Next pages through ordinary activity and roster refreshes", () => {
    const agents = members();
    const selected = agents[0].agent_id;
    const previous = { ids: agents.map((agent) => agent.agent_id), selected };
    const updated = agents.map((agent, index) => ({
      ...agent,
      seq: 500 + index,
      activity: "executing" as const,
    }));
    for (const page of [0, 1])
      expect(
        followRosterPage({
          agents: updated,
          page,
          perPage,
          selected,
          previous,
        }),
      ).toBe(page);
  });
  it("follows an actual explicit selection change, including a warning avatar", () => {
    const agents = members();
    const previous = {
      ids: agents.map((agent) => agent.agent_id),
      selected: agents[0].agent_id,
    };
    const selected = agents[perPage].agent_id;
    expect(
      followRosterPage({
        agents,
        page: 1,
        perPage,
        selected: agents[0].agent_id,
      }),
    ).toBe(0);
    expect(
      followRosterPage({
        agents: agents.map((agent) => ({ ...agent, activity: "error" })),
        page: 0,
        perPage,
        selected,
        previous,
      }),
    ).toBe(1);
    expect(
      followRosterPage({
        agents,
        page: 1,
        perPage,
        selected: agents[0].agent_id,
        previous: { ...previous, selected },
      }),
    ).toBe(0);
  });
  it("does not follow a newly observed error or lose paging when agents disappear", () => {
    const agents = members();
    const selected = agents[0].agent_id;
    const previous = {
      ids: agents.slice(0, perPage).map((agent) => agent.agent_id),
      selected,
    };
    expect(
      followRosterPage({
        agents: agents.map((agent, index) => ({
          ...agent,
          activity: index === perPage ? "error" : "completed",
        })),
        page: 0,
        perPage,
        selected,
        previous,
      }),
    ).toBe(0);
    expect(
      followRosterPage({
        agents: agents.slice(0, perPage),
        page: 1,
        perPage,
        selected,
        previous: { ids: agents.map((agent) => agent.agent_id), selected },
      }),
    ).toBe(0);
  });
});
