import { isExternalAgent, roleFor } from "./office";
import type { AgentActivity, Artifact } from "./types";

export function artifactActor(artifact: Artifact): string | undefined {
  if (typeof artifact.scope !== "string" || !artifact.scope) return undefined;
  try {
    const scope: unknown = JSON.parse(artifact.scope);
    if (
      !Array.isArray(scope) ||
      scope.length !== 3 ||
      typeof scope[0] !== "string" ||
      !scope[0].trim() ||
      !Number.isSafeInteger(scope[1]) ||
      scope[1] < 0 ||
      typeof scope[2] !== "string" ||
      !scope[2].trim()
    )
      return undefined;
    return scope[2];
  } catch {
    return undefined;
  }
}

export function scopedAgentArtifacts(
  agent: AgentActivity,
  artifacts: Artifact[],
  runId = agent.run_id,
): {
  owned: Artifact[];
  context: Artifact[];
  contextLabel?: string;
} {
  if (isExternalAgent(agent)) return { owned: [], context: [] };
  const available = artifacts.filter(
    (file) => !runId || !file.run_id || file.run_id === runId,
  );
  const owned = available.filter(
    (file) => artifactActor(file) === agent.agent_id,
  );
  const others = available.filter((file) => !owned.includes(file));
  const role = roleFor(agent);
  if (role.kind === "specialist" || agent.agent_id === "tools_rd_lead")
    return { owned, context: [] };
  if (
    ["planner", "executive", "research_head", "engineering_head"].includes(
      agent.agent_id,
    )
  ) {
    return {
      owned,
      context: agent.kr_id
        ? others.filter((file) => file.kr_id === agent.kr_id)
        : others,
      contextLabel: agent.kr_id ? "Key result context" : "Mission context",
    };
  }
  if (agent.agent_id.endsWith("_gatekeeper"))
    return {
      owned,
      context: agent.kr_id
        ? others.filter((file) => file.kr_id === agent.kr_id)
        : [],
      contextLabel: "Key result context",
    };
  const worker = [
    "market_researcher",
    "data_analyst",
    "system_architect",
    "backend_coder",
  ].includes(agent.agent_id);
  return {
    owned,
    context:
      worker && agent.kr_id
        ? others.filter(
            (file) =>
              file.kr_id === agent.kr_id &&
              (file.scope === undefined ||
                file.scope === null ||
                file.scope === ""),
          )
        : [],
    contextLabel: "Legacy key result context · author not recorded",
  };
}
