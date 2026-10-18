import type { ModelConfig, WorkspaceSettings } from "./types";
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
