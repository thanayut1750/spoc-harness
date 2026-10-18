import { describe, expect, it } from "vitest";
import {
  appendEvent,
  initialAgents,
  normalizeAgent,
  parseActivityEvent,
  projectEvent,
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
    expect(Object.keys(agents)).toHaveLength(10);
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
});
