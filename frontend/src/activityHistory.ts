import { isExternalAgent } from "./office";
import type { ActivityEvent, ActivityScope, AgentActivity } from "./types";

export function agentActivityScope(
  agent: AgentActivity,
  runId?: string,
): ActivityScope {
  return {
    source: agent.source || "harness",
    agent_id: agent.original_agent_id || agent.agent_id,
    ...(!isExternalAgent(agent) && runId ? { run_id: runId } : {}),
  };
}

export function activityMatches(event: ActivityEvent, scope: ActivityScope) {
  return (
    (!scope.run_id || event.run_id === scope.run_id) &&
    (!scope.source || event.source === scope.source) &&
    (!scope.agent_id ||
      (event.original_agent_id || event.agent_id) === scope.agent_id)
  );
}

// Persisted history and live events share a durable sequence, but may overlap.
// Keep this uncapped: older pages must stay reachable after the live buffer fills.
export function mergeActivity(
  persisted: ActivityEvent[],
  live: ActivityEvent[],
  scope: ActivityScope = {},
) {
  const sequences = new Set<number>();
  const identities = new Set<string>();
  return [...live, ...persisted]
    .filter((event) => activityMatches(event, scope))
    .sort((a, b) => b.seq - a.seq)
    .filter((event) => {
      const identity = JSON.stringify([event.source, event.event_id]);
      if (sequences.has(event.seq) || identities.has(identity)) return false;
      sequences.add(event.seq);
      identities.add(identity);
      return true;
    });
}
