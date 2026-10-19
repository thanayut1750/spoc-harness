import type {
  AgentActivity,
  Artifact,
  ResumeInput,
  Run,
  RunInput,
  ModelConfig,
  WorkspaceSettings,
  RegenesisResult,
  ActivityScope,
  ActivityPage,
  ModelCallBudget,
} from "./types";
import { normalizeAgent, parseActivityEvent } from "./office";
async function responseFor(
  path: string,
  body?: unknown,
  method = body === undefined ? "GET" : "POST",
  accept = "application/json",
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers:
        body === undefined
          ? { Accept: accept }
          : { "Content-Type": "application/json", Accept: accept },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new Error(
      "Could not reach the harness. Check the connection and refresh the mission status.",
    );
  }
  if (!response.ok) {
    let message = `The harness could not complete this request (${response.status}).`;
    try {
      const error = await response.json();
      message =
        typeof error?.detail === "string" && error.detail.trim()
          ? error.detail
          : Array.isArray(error?.detail)
            ? error.detail
                .filter((issue: unknown) => issue && typeof issue === "object")
                .slice(0, 3)
                .map(
                  (issue: { loc?: unknown[]; msg?: unknown }) =>
                    `${Array.isArray(issue.loc) ? issue.loc.slice(1).join(".") || "Request" : "Request"}: ${String(issue.msg || "Invalid value")}`,
                )
                .join("; ") || message
            : typeof error?.message === "string" && error.message.trim()
              ? error.message
              : message;
    } catch {
      /* retain safe HTTP error */
    }
    throw new Error(message);
  }
  return response;
}
async function request<T>(
  path: string,
  body?: unknown,
  method = body === undefined ? "GET" : "POST",
): Promise<T> {
  const response = await responseFor(path, body, method);
  if (response.status === 204) return undefined as T;
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error(
      "The harness returned an unreadable response. Refresh the mission status to check whether the request completed.",
    );
  }
}
export const api = {
  settings: () => request<WorkspaceSettings>("/settings"),
  saveModel: (config: ModelConfig) =>
    request<WorkspaceSettings>("/settings/model", config, "PUT"),
  saveCallBudget: (budget: ModelCallBudget) =>
    request<WorkspaceSettings>("/settings/budgets", budget, "PUT"),
  saveAgentModel: (agentId: string, config: ModelConfig) =>
    request<WorkspaceSettings>(
      `/settings/agents/${encodeURIComponent(agentId)}`,
      config,
      "PUT",
    ),
  removeAgentModel: (agentId: string) =>
    request<WorkspaceSettings>(
      `/settings/agents/${encodeURIComponent(agentId)}`,
      undefined,
      "DELETE",
    ),
  regenesis: (confirmation: string) =>
    request<RegenesisResult>("/regenesis", { confirmation }),
  office: () =>
    request<{ agents: AgentActivity[]; cursor: number; generation?: string }>(
      "/office",
    ),
  history: async (
    scope: ActivityScope,
    before?: number,
    generation?: string,
  ): Promise<ActivityPage> => {
    const query = new URLSearchParams({ limit: "100" });
    for (const [key, value] of Object.entries(scope))
      if (value) query.set(key, value);
    if (before !== undefined) query.set("before", String(before));
    if (generation) query.set("generation", generation);
    const page = await request<ActivityPage>(`/events/history?${query}`);
    if (
      !page ||
      !Array.isArray(page.events) ||
      typeof page.has_more !== "boolean" ||
      !(
        page.next_before === null ||
        (Number.isSafeInteger(page.next_before) && page.next_before > 0)
      ) ||
      (page.has_more &&
        (page.next_before === null ||
          (before !== undefined && page.next_before >= before)))
    )
      throw new Error("The harness returned invalid activity history.");
    const events = page.events.map((event) => {
      const parsed = parseActivityEvent(JSON.stringify(event));
      if (!parsed)
        throw new Error("The harness returned invalid activity history.");
      return normalizeAgent(parsed);
    });
    return { ...page, events };
  },
  runs: async () => {
    const data = await request<Run[] | { runs: Run[] }>("/runs");
    const runs = Array.isArray(data) ? data : data?.runs;
    if (!Array.isArray(runs))
      throw new Error("The harness returned an invalid mission list.");
    return runs;
  },
  run: (id: string) => request<Run>(`/runs/${encodeURIComponent(id)}`),
  retry: (id: string) =>
    request<Run>(`/runs/${encodeURIComponent(id)}/retry`, undefined, "POST"),
  create: (input: RunInput) =>
    request<{ run_id: string; status: string }>("/runs", input),
  control: (id: string, action: "pause" | "cancel") =>
    request<unknown>(`/runs/${encodeURIComponent(id)}/${action}`, {}),
  resume: (id: string, input: ResumeInput) =>
    request<unknown>(`/runs/${encodeURIComponent(id)}/resume`, input),
  note: (id: string, content: string, agent_id?: string) =>
    request<unknown>(`/runs/${encodeURIComponent(id)}/notes`, {
      content,
      ...(agent_id ? { agent_id } : {}),
    }),
  artifacts: async (id: string) => {
    const files = await request<Artifact[]>(
      `/runs/${encodeURIComponent(id)}/artifacts`,
    );
    if (!Array.isArray(files))
      throw new Error("The harness returned an invalid file list.");
    return files;
  },
  downloadArtifact: async (id: string) => {
    const response = await responseFor(
      `/artifacts/${encodeURIComponent(id)}`,
      undefined,
      "GET",
      "*/*",
    );
    try {
      return await response.blob();
    } catch {
      throw new Error("The file download was interrupted. Download it again.");
    }
  },
};
