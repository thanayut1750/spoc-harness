import type {
  AgentActivity,
  Artifact,
  ResumeInput,
  Run,
  RunInput,
} from "./types";
async function request<T>(
  path: string,
  body?: unknown,
  method = body === undefined ? "GET" : "POST",
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers:
      body === undefined
        ? { Accept: "application/json" }
        : { "Content-Type": "application/json", Accept: "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const error = await response.json();
      message =
        typeof error.detail === "string"
          ? error.detail
          : Array.isArray(error.detail)
            ? error.detail
                .slice(0, 3)
                .map(
                  (issue: { loc?: unknown[]; msg?: unknown }) =>
                    `${issue.loc?.slice(1).join(".") || "Request"}: ${String(issue.msg || "Invalid value")}`,
                )
                .join("; ")
            : typeof error.message === "string"
              ? error.message
              : message;
    } catch {
      /* retain safe HTTP error */
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
export const api = {
  office: () => request<{ agents: AgentActivity[]; cursor: number }>("/office"),
  runs: async () => {
    const data = await request<Run[] | { runs: Run[] }>("/runs");
    return Array.isArray(data) ? data : data.runs;
  },
  run: (id: string) => request<Run>(`/runs/${encodeURIComponent(id)}`),
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
  artifacts: (id: string) =>
    request<Artifact[]>(`/runs/${encodeURIComponent(id)}/artifacts`),
};
