import { describe, expect, it } from "vitest";
import {
  confirmsRegenesis,
  selectProvider,
  validModelConfig,
  agentModelSelection,
} from "./modelSettings";
import type { AgentActivity, Run, WorkspaceSettings } from "./types";
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
  worker_timeout: 3600,
  model_call_budget: { max_model_calls: 100, worker_model_calls: 12 },
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
  it("inherits the specialist base-role snapshot and supports an independent Tools R&D override", () => {
    const specialist: AgentActivity = {
      agent_id: "specialist:run:1234567890abcdef",
      source: "harness",
      activity: "writing",
      data: {
        agent_type: "engineering_specialist",
        model_parent: "backend_coder",
      },
    };
    const override = {
      provider: "zai",
      model: "specialist-model",
      reasoning_effort: "high",
    };
    const run: Run = {
      run_id: "run",
      status: "running",
      user_request: "Build a scene",
      model_config: settings.model_config,
      agent_model_configs: { backend_coder: override, tools_rd_lead: override },
    };
    expect(agentModelSelection(specialist, run)).toEqual({
      config: override,
      inheritedFrom: "Backend coder",
    });
    expect(
      agentModelSelection(specialist, { ...run, agent_model_configs: {} })
        ?.config,
    ).toBe(run.model_config);
    expect(
      agentModelSelection(
        {
          ...specialist,
          data: {
            agent_type: "research_specialist",
            model_parent: "data_analyst",
          },
        },
        { ...run, agent_model_configs: { data_analyst: override } },
      ),
    ).toEqual({ config: override, inheritedFrom: "Data analyst" });
    expect(
      agentModelSelection({ ...specialist, source: "external" }, run),
    ).toBeUndefined();
    expect(
      agentModelSelection(
        { agent_id: "triage_router", source: "harness", activity: "completed" },
        run,
      ),
    ).toBeUndefined();
    expect(
      agentModelSelection({ agent_id: "tools_rd_lead", activity: "idle" }, run)
        ?.config,
    ).toBe(override);
  });
});
it("requires the exact deliberate Regenesis confirmation", () => {
  expect(confirmsRegenesis("REGENESIS")).toBe(true);
  for (const input of ["", "regenesis", " REGENESIS", "REGENESIS ", "RESET"])
    expect(confirmsRegenesis(input)).toBe(false);
});
