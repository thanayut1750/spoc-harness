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
    "Failed to fetch",
  );
});
