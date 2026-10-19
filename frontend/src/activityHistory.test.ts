import { describe, expect, it } from "vitest";
import {
  activityMatches,
  agentActivityScope,
  mergeActivity,
} from "./activityHistory";
import { normalizeAgent } from "./office";
import type { ActivityEvent } from "./types";

const event = (
  seq: number,
  extra: Partial<ActivityEvent> = {},
): ActivityEvent => ({
  seq,
  event_id: `event-${seq}`,
  source: "harness",
  agent_id: "backend_coder",
  run_id: "mission-a",
  activity: "writing",
  timestamp: "2026-10-19T09:00:00Z",
  ...extra,
});

describe("durable activity history", () => {
  it("merges overlapping persisted pages and live deliveries without truncating earlier history", () => {
    const persisted = Array.from({ length: 300 }, (_, index) =>
      event(index + 1),
    );
    const merged = mergeActivity(persisted, [
      event(301),
      event(300),
      event(299),
    ]);
    expect(merged).toHaveLength(301);
    expect(merged[0].seq).toBe(301);
    expect(merged.at(-1)?.seq).toBe(1);
    expect(
      mergeActivity(merged, [event(302, { event_id: "event-301" })]),
    ).toHaveLength(301);
  });

  it("isolates a selected mission and actual agent while preserving external source identity", () => {
    const own = event(1);
    const olderMission = event(2, { run_id: "mission-b" });
    const sibling = event(3, { agent_id: "system_architect" });
    const external = normalizeAgent(
      event(4, { source: "custom", run_id: undefined }),
    );
    const scope = agentActivityScope(own, "mission-a");
    expect(
      mergeActivity([own, olderMission, sibling, external], [], scope),
    ).toEqual([own]);
    expect(agentActivityScope(external, "mission-a")).toEqual({
      source: "custom",
      agent_id: "backend_coder",
    });
    expect(activityMatches(own, agentActivityScope(external))).toBe(false);
    expect(activityMatches(external, agentActivityScope(external))).toBe(true);
  });

  it("keeps identical event IDs independent across sources without mutating their identities", () => {
    const internal = event(1, { event_id: "shared" });
    const external = normalizeAgent(
      event(2, { event_id: "shared", source: "office" }),
    );
    const merged = mergeActivity([internal], [external]);
    expect(merged).toEqual([external, internal]);
    expect(internal.agent_id).toBe("backend_coder");
    expect(external.agent_id).toBe("office:backend_coder");
  });
});
