import type {
  AgentActivity,
  ModelConfig,
  Run,
  WorkspaceSettings,
} from "./types";
import { isExternalAgent, roleFor, roles } from "./office";
export function agentModelSelection(
  agent: AgentActivity,
  run: Run | null,
): { config: ModelConfig; inheritedFrom?: string } | undefined {
  if (!run?.model_config || isExternalAgent(agent)) return undefined;
  const role = roleFor(agent);
  if (role.kind === "internal") return undefined;
  if (role.kind === "specialist") {
    const parent = roles.find((item) => item.id === role.model_parent);
    return {
      config:
        (parent && run.agent_model_configs?.[parent.id]) || run.model_config,
      inheritedFrom: parent?.name ?? "mission default",
    };
  }
  return {
    config: run.agent_model_configs?.[agent.agent_id] ?? run.model_config,
  };
}
export function selectProvider(
  settings: WorkspaceSettings,
  providerId: string,
  current: ModelConfig,
): ModelConfig {
  const provider = settings.providers.find((item) => item.id === providerId);
  if (!provider?.configured) return current;
  return {
    provider: provider.id,
    model: provider.default_model,
    reasoning_effort: provider.reasoning_efforts.includes(
      current.reasoning_effort,
    )
      ? current.reasoning_effort
      : (provider.reasoning_efforts[0] ?? settings.defaults.reasoning_effort),
  };
}
export function validModelConfig(
  settings: WorkspaceSettings,
  config: ModelConfig,
): boolean {
  const provider = settings.providers.find(
    (item) => item.id === config.provider,
  );
  return (
    !!provider?.configured &&
    !!config.model.trim() &&
    !!config.reasoning_effort.trim() &&
    (!provider.reasoning_efforts.length ||
      provider.reasoning_efforts.includes(config.reasoning_effort))
  );
}
export function confirmsRegenesis(value: string): boolean {
  return value === "REGENESIS";
}
