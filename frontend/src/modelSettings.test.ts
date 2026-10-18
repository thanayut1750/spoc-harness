import { describe, expect, it } from "vitest";
import {
  confirmsRegenesis,
  selectProvider,
  validModelConfig,
} from "./modelSettings";
import type { WorkspaceSettings } from "./types";
const settings: WorkspaceSettings = {
  defaults: {
    provider: "configured",
    model: "default-model",
    reasoning_effort: "max",
  },
  model_config: {
    provider: "configured",
    model: "default-model",
    reasoning_effort: "max",
  },
  providers: [
    {
      id: "configured",
      label: "Environment provider",
      configured: true,
      default_model: "default-model",
      reasoning_efforts: ["high", "max"],
    },
    {
      id: "zai",
      label: "Z.AI",
      configured: true,
      default_model: "glm-5.3-flash",
      reasoning_efforts: ["high"],
    },
    {
      id: "openai",
      label: "OpenAI",
      configured: false,
      default_model: "example",
      reasoning_efforts: ["high"],
    },
  ],
  triage: { model: "jev-1.13.0", configured: true },
  worker_timeout: 180,
};
describe("model selection", () => {
  it("does not switch into an unconfigured provider or accept its model configuration", () => {
    expect(selectProvider(settings, "openai", settings.model_config)).toBe(
      settings.model_config,
    );
    expect(
      validModelConfig(settings, {
        provider: "openai",
        model: "anything",
        reasoning_effort: "high",
      }),
    ).toBe(false);
  });
  it("selects a provider default and a supported reasoning level while preserving custom model names", () => {
    expect(selectProvider(settings, "zai", settings.model_config)).toEqual({
      provider: "zai",
      model: "glm-5.3-flash",
      reasoning_effort: "high",
    });
    expect(
      validModelConfig(settings, {
        provider: "configured",
        model: "custom-model",
        reasoning_effort: "max",
      }),
    ).toBe(true);
    expect(
      validModelConfig(settings, {
        provider: "configured",
        model: " ",
        reasoning_effort: "max",
      }),
    ).toBe(false);
  });
});
it("requires the exact deliberate Regenesis confirmation", () => {
  expect(confirmsRegenesis("REGENESIS")).toBe(true);
  for (const input of ["", "regenesis", " REGENESIS", "REGENESIS ", "RESET"])
    expect(confirmsRegenesis(input)).toBe(false);
});
