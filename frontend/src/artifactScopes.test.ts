import { describe, expect, it } from "vitest";
import { artifactActor, scopedAgentArtifacts } from "./artifactScopes";
import type { AgentActivity, Artifact } from "./types";

const alpha: AgentActivity = {
  agent_id: "specialist:run:aaaaaaaaaaaaaaaa",
  source: "harness",
  activity: "writing",
  run_id: "run",
  kr_id: "KR1",
  data: { agent_type: "engineering_specialist" },
};
const beta = { ...alpha, agent_id: "specialist:run:bbbbbbbbbbbbbbbb" };
const file = (
  id: string,
  actor?: string,
  extras: Partial<Artifact> = {},
): Artifact => ({
  artifact_id: id,
  name: `${id}.json`,
  media_type: "application/json",
  run_id: "run",
  kr_id: "KR1",
  ...(actor ? { scope: JSON.stringify([`work-${id}`, 0, actor]) } : {}),
  ...extras,
});

describe("artifact authorship", () => {
  it("uses only a valid server scope tuple as an actor claim", () => {
    expect(artifactActor(file("valid", alpha.agent_id))).toBe(alpha.agent_id);
    for (const scope of [
      undefined,
      null,
      "",
      "not-json",
      JSON.stringify({ actor: alpha.agent_id }),
      JSON.stringify(["work", alpha.agent_id]),
      JSON.stringify(["work", "0", alpha.agent_id]),
      JSON.stringify(["work", -1, alpha.agent_id]),
      JSON.stringify(["work", 0, { actor: alpha.agent_id }]),
      JSON.stringify(["", 0, alpha.agent_id]),
      JSON.stringify(["work", 0, alpha.agent_id, alpha.agent_id]),
    ]) {
      expect(
        artifactActor(file("invalid", undefined, { scope })),
      ).toBeUndefined();
    }
  });
  it("isolates sibling specialists and Tools R&D without global or legacy fallbacks", () => {
    const files = [
      file("alpha", alpha.agent_id),
      file("beta", beta.agent_id),
      file("legacy"),
      file("malformed", undefined, {
        scope: JSON.stringify({ actor: alpha.agent_id }),
      }),
      file("foreign", alpha.agent_id, { run_id: "other-run" }),
    ];
    expect(scopedAgentArtifacts(alpha, files)).toMatchObject({
      owned: [files[0]],
      context: [],
    });
    expect(scopedAgentArtifacts(beta, files)).toMatchObject({
      owned: [files[1]],
      context: [],
    });
    expect(
      scopedAgentArtifacts(
        { ...alpha, data: { agent_type: "research_specialist" } },
        files,
      ),
    ).toMatchObject({ owned: [files[0]], context: [] });
    const rd: AgentActivity = { agent_id: "tools_rd_lead", activity: "idle" };
    expect(scopedAgentArtifacts(rd, files, "run")).toEqual({
      owned: [],
      context: [],
    });
    const rdFile = file("rd", "tools_rd_lead");
    expect(scopedAgentArtifacts(rd, [...files, rdFile], "run")).toEqual({
      owned: [rdFile],
      context: [],
    });
    expect(
      scopedAgentArtifacts({ ...alpha, source: "external" }, files),
    ).toEqual({ owned: [], context: [] });
  });
  it("keeps idle builtin workers empty and labels assigned legacy context without claiming ownership", () => {
    const files = [
      file("own", "backend_coder"),
      file("legacy"),
      file("sibling", beta.agent_id),
      file("other-kr", undefined, { kr_id: "KR2" }),
      file("global", undefined, { kr_id: undefined }),
      file("malformed", undefined, { scope: "broken" }),
    ];
    expect(
      scopedAgentArtifacts(
        { agent_id: "system_architect", activity: "idle" },
        files,
      ).context,
    ).toEqual([]);
    const worker: AgentActivity = {
      agent_id: "backend_coder",
      activity: "writing",
      kr_id: "KR1",
    };
    const scoped = scopedAgentArtifacts(worker, files, "run");
    expect(scoped.owned).toEqual([files[0]]);
    expect(scoped.context).toEqual([files[1]]);
    expect(scoped.contextLabel).toContain("author not recorded");
  });
  it("retains explicit mission and key-result context for leads and assigned reviewers", () => {
    const files = [
      file("worker", alpha.agent_id),
      file("other-kr", beta.agent_id, { kr_id: "KR2" }),
    ];
    expect(
      scopedAgentArtifacts({ agent_id: "executive", activity: "idle" }, files),
    ).toMatchObject({
      owned: [],
      context: files,
      contextLabel: "Mission context",
    });
    expect(
      scopedAgentArtifacts(
        {
          agent_id: "engineering_gatekeeper",
          activity: "reviewing",
          kr_id: "KR1",
        },
        files,
      ),
    ).toMatchObject({
      owned: [],
      context: [files[0]],
      contextLabel: "Key result context",
    });
    expect(
      scopedAgentArtifacts(
        { agent_id: "engineering_gatekeeper", activity: "idle" },
        files,
      ).context,
    ).toEqual([]);
  });
});
