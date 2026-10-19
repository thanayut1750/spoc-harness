import { describe, expect, it } from "vitest";
import {
  eligibleAgentEvent,
  layoutAgentEvents,
  recordedAgentEvent,
} from "./agentEvent";
import { initialAgents, officeRoster, normalizeAgent } from "./office";
import type { AgentActivity } from "./types";
const recorded = (
  agent_id: string,
  extra: Partial<AgentActivity> = {},
): AgentActivity => ({
  agent_id,
  source: "harness",
  seq: 1,
  activity: "writing",
  summary: "Writing the verified task output with sources",
  timestamp: "2026-10-20T08:00:00Z",
  ...extra,
});
const agents = [
  ...Object.keys(initialAgents()).map((id) => recorded(id)),
  recorded("triage_router"),
  ...Array.from({ length: 4 }, (_, index) =>
    recorded(`specialist:run:${index}`, {
      data: {
        agent_type: "engineering_specialist",
        display_name: `Specialist ${index}`,
      },
    }),
  ),
  ...Array.from({ length: 3 }, (_, index) =>
    normalizeAgent(recorded(`external-${index}`, { source: "custom" })),
  ),
];
describe("recorded event bubbles", () => {
  it("distinguishes real idle, completed, and failed events from initial placeholders", () => {
    expect(recordedAgentEvent(initialAgents().planner)).toBe(false);
    expect(recordedAgentEvent(recorded("planner", { activity: "idle" }))).toBe(
      true,
    );
    expect(
      recordedAgentEvent(
        recorded("planner", { seq: undefined, timestamp: "invalid" }),
      ),
    ).toBe(false);
    const events = [
      recorded("planner", { activity: "completed" }),
      recorded("executive", { activity: "error" }),
    ];
    const { bubbles } = layoutAgentEvents(
      officeRoster(events).positioned,
      events,
      900,
      520,
    );
    expect(bubbles.map((bubble) => bubble.label)).toEqual(["Completed"]);
    expect(bubbles[0].title).toContain(events[0].summary);
    // Suppressing an error bubble does not delete its avatar or recorded fact.
    expect(officeRoster(events).positioned).toHaveLength(2);
    expect(recordedAgentEvent(events[1])).toBe(true);
  });
  it.each([
    [579, 500],
    [900, 500],
    [800, 520],
  ])(
    "keeps19 recorded bubbles separate and inside a %ix%i map",
    (width, height) => {
      const { bubbles, tooSmall } = layoutAgentEvents(
        officeRoster(agents).positioned,
        agents,
        width,
        height,
      );
      expect(tooSmall).toBe(false);
      expect(bubbles).toHaveLength(19);
      for (const bubble of bubbles) {
        expect(bubble.x).toBeGreaterThanOrEqual(0);
        expect(bubble.y).toBeGreaterThanOrEqual(0);
        expect(bubble.x + bubble.width).toBeLessThanOrEqual(width);
        expect(bubble.y + bubble.height).toBeLessThanOrEqual(height);
      }
      for (let index = 0; index < bubbles.length; index++)
        for (const other of bubbles.slice(index + 1)) {
          const bubble = bubbles[index];
          expect(
            bubble.x + bubble.width <= other.x ||
              other.x + other.width <= bubble.x ||
              bubble.y + bubble.height <= other.y ||
              other.y + other.height <= bubble.y,
            `${bubble.agent.agent_id} and ${other.agent.agent_id}`,
          ).toBe(true);
        }
    },
  );
  it("uses raw snapshot summaries without changing displayed avatar state or external identity", () => {
    const source = recorded("backend_coder", {
      activity: "reading",
      summary: "Source could not be read; trying another citation",
    });
    const external = normalizeAgent(
      recorded("backend_coder", {
        source: "custom",
        summary: "External result",
      }),
    );
    const displayed = {
      ...source,
      activity: "completed" as const,
      summary: "Derived run status",
    };
    const { bubbles } = layoutAgentEvents(
      officeRoster([displayed, external]).positioned,
      [source, external],
      900,
      520,
    );
    expect(
      bubbles.find((b) => b.agent.agent_id === source.agent_id)?.summary,
    ).toBe(source.summary);
    expect(
      bubbles.find((b) => b.agent.agent_id === external.agent_id)?.summary,
    ).toBe("External result");
    expect(displayed.summary).toBe("Derived run status");
  });
  it("hides warning bubbles from either actual or displayed error state and restores them after recovery", () => {
    const rawError = recorded("executive", { activity: "error" });
    const derivedError = recorded("backend_coder", { activity: "executing" });
    const external = normalizeAgent(
      recorded("external-error", { source: "integration", activity: "error" }),
    );
    const records = [rawError, derivedError, external];
    const displayed = [
      { ...rawError, activity: "completed" as const },
      { ...derivedError, activity: "error" as const },
      external,
    ];
    for (let index = 0; index < displayed.length; index++)
      expect(eligibleAgentEvent(displayed[index], records[index])).toBe(false);
    expect(
      layoutAgentEvents(officeRoster(displayed).positioned, records, 900, 520)
        .bubbles,
    ).toEqual([]);
    expect(officeRoster(displayed).positioned).toHaveLength(3);
    const recovered = records.map((agent) => ({
      ...agent,
      activity: "completed" as const,
      seq: 20,
    }));
    const layout = layoutAgentEvents(
      officeRoster(recovered).positioned,
      recovered,
      900,
      520,
    );
    expect(layout.bubbles).toHaveLength(3);
    expect(
      recovered.filter((agent) => eligibleAgentEvent(agent, agent)),
    ).toHaveLength(layout.bubbles.length);
  });
  it.each([560, 579])(
    "reports insufficient space and fits19 with real pager obstacles after inner height grows at width%i",
    (width) => {
      let height = 500;
      const controls = () => [
        { x: 7, y: height - 41, width: 196, height: 34 },
        { x: width - 256, y: height - 41, width: 249, height: 34 },
      ];
      let layout = layoutAgentEvents(
        officeRoster(agents).positioned,
        agents,
        width,
        height,
        controls(),
      );
      expect(layout.tooSmall).toBe(true);
      for (let retry = 0; layout.tooSmall && retry < 8; retry++) {
        height += 64;
        layout = layoutAgentEvents(
          officeRoster(agents).positioned,
          agents,
          width,
          height,
          controls(),
        );
      }
      expect(layout.tooSmall).toBe(false);
      expect(layout.bubbles).toHaveLength(19);
      expect(height).toBeLessThanOrEqual(756);
    },
  );
  it("returns a bounded too-small result for invalid and sub-card geometry", () => {
    for (const [width, height] of [
      [10, 3],
      [0, 0],
      [NaN, 500],
      [500, Infinity],
    ])
      expect(
        layoutAgentEvents(
          officeRoster(agents).positioned,
          agents,
          width,
          height,
        ),
      ).toEqual({ bubbles: [], tooSmall: true });
  });
  it("fits the live seven-event office at 551x400 without requiring overflow", () => {
    const ids = new Set([
      "executive",
      "engineering_head",
      "engineering_gatekeeper",
      "tools_rd_lead",
      "triage_router",
      "specialist:run:0",
      "specialist:run:1",
    ]);
    const records = agents.filter((agent) => ids.has(agent.agent_id));
    const positioned = officeRoster([
      ...Object.values(initialAgents()),
      ...records.filter(
        (agent) => !Object.hasOwn(initialAgents(), agent.agent_id),
      ),
    ]).positioned;
    const layout = layoutAgentEvents(positioned, records, 551, 400, [
      { x: 294, y: 359, width: 250, height: 34 },
    ]);
    expect(layout.tooSmall).toBe(false);
    expect(layout.bubbles).toHaveLength(7);
    expect(
      layout.bubbles.every((bubble) => bubble.title.startsWith(bubble.name)),
    ).toBe(true);
  });
});
