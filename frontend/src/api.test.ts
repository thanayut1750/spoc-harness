import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";
afterEach(() => vi.unstubAllGlobals());
it("surfaces field-specific API validation failures to the operator", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [
            {
              loc: ["body", "workspace_path"],
              msg: "Directory does not exist",
            },
          ],
        }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );
  await expect(api.create({ user_request: "Build a tool" })).rejects.toThrow(
    "workspace_path: Directory does not exist",
  );
});
it("does not treat an unavailable service as an accepted command", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
  );
  await expect(api.control("run-1", "pause")).rejects.toThrow(
    "Could not reach the harness. Check the connection and refresh the mission status.",
  );
});
it("keeps non-JSON HTTP failures readable without exposing an HTML error page", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response("<html>Proxy failure</html>", { status: 502 }),
      ),
  );
  await expect(api.settings()).rejects.toThrow(
    "The harness could not complete this request (502).",
  );
});
it("treats an unreadable success response as an unknown outcome rather than retrying it", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(new Response("not-json", { status: 202 }));
  vi.stubGlobal("fetch", fetch);
  await expect(api.retry("run-1")).rejects.toThrow(
    "Refresh the mission status to check whether the request completed.",
  );
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("rejects invalid list responses before they reach the UI", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ error: "unavailable" })),
    )
    .mockResolvedValueOnce(new Response("null"));
  vi.stubGlobal("fetch", fetch);
  await expect(api.runs()).rejects.toThrow("invalid mission list");
  await expect(api.artifacts("run-1")).rejects.toThrow("invalid file list");
});
it("surfaces missing artifact content and preserves successful download bytes", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "Artifact content is unavailable" }),
        { status: 404 },
      ),
    )
    .mockResolvedValueOnce(
      new Response("verified output", {
        headers: { "Content-Type": "text/plain" },
      }),
    );
  vi.stubGlobal("fetch", fetch);
  await expect(api.downloadArtifact("missing-file")).rejects.toThrow(
    "Artifact content is unavailable",
  );
  const content = await api.downloadArtifact("available-file");
  expect(await content.text()).toBe("verified output");
  expect(fetch).toHaveBeenLastCalledWith("/api/artifacts/available-file", {
    method: "GET",
    headers: { Accept: "*/*" },
  });
});
it("retries the existing failed run through its recovery endpoint without a request body", async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ run_id: "failed-run", status: "queued" }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetch);
  await expect(api.retry("failed-run")).resolves.toMatchObject({
    run_id: "failed-run",
    status: "queued",
  });
  expect(fetch).toHaveBeenCalledWith("/api/runs/failed-run/retry", {
    method: "POST",
    headers: { Accept: "application/json" },
  });
});
it("requests a bounded earlier history page with exact source, actor, mission, and generation filters", async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        events: [
          {
            event_id: "saved",
            seq: 3,
            source: "custom",
            agent_id: "backend_coder",
            activity: "reading",
            timestamp: "2026-10-19T09:00:00Z",
          },
        ],
        has_more: false,
        next_before: null,
        generation: "generation-a",
      }),
    ),
  );
  vi.stubGlobal("fetch", fetch);
  const result = await api.history(
    { run_id: "mission / a", source: "custom", agent_id: "backend_coder" },
    9,
    "generation-a",
  );
  expect(fetch.mock.calls[0][0]).toBe(
    "/api/events/history?limit=100&run_id=mission+%2F+a&source=custom&agent_id=backend_coder&before=9&generation=generation-a",
  );
  expect(result.events[0].agent_id).toBe("custom:backend_coder");
  expect(result.events[0].original_agent_id).toBe("backend_coder");
});
it("rejects malformed history and nonadvancing pagination instead of silently hiding activity", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({ events: [], has_more: true, next_before: 10 }),
      ),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          events: [{ seq: 1 }],
          has_more: false,
          next_before: null,
        }),
      ),
    );
  vi.stubGlobal("fetch", fetch);
  await expect(api.history({}, 10)).rejects.toThrow("invalid activity history");
  await expect(api.history({})).rejects.toThrow("invalid activity history");
});
