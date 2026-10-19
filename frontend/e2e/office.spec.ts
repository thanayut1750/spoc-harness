import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { Artifact, Run, WorkspaceSettings } from "../src/types";
const runId = "run-fixture";
const defaultSettings: WorkspaceSettings = {
  defaults: {
    provider: "configured",
    model: "glm-5.3-flash",
    reasoning_effort: "max",
  },
  model_config: {
    provider: "configured",
    model: "glm-5.3-flash",
    reasoning_effort: "max",
  },
  providers: [
    {
      id: "configured",
      label: "Environment provider",
      configured: true,
      default_model: "glm-5.3-flash",
      reasoning_efforts: ["low", "high", "max"],
    },
    {
      id: "zai",
      label: "Z.AI",
      configured: true,
      default_model: "glm-5.3-flash",
      reasoning_efforts: ["low", "high", "max"],
    },
    {
      id: "openai",
      label: "OpenAI",
      configured: false,
      default_model: "openai-model",
      reasoning_efforts: ["low", "high"],
    },
  ],
  triage: { model: "jev-1.13.0", configured: true },
  worker_timeout: 180,
  agent_model_configs: {},
};
const initialRun: Run = {
  run_id: runId,
  status: "running",
  user_request: "Research and build a durable planning tool",
  objectives: [
    {
      objective_id: "O1",
      title: "Build a useful planning tool",
      key_results: [
        {
          kr_id: "KR1",
          description: "Research validated user needs",
          target_department: "research",
          acceptance_criteria: ["Cite three sources"],
          dependency_kr_ids: [],
          version: 1,
        },
        {
          kr_id: "KR2",
          description: "Build and test the planning API",
          target_department: "engineering",
          acceptance_criteria: ["Tests pass"],
          dependency_kr_ids: ["KR1"],
          version: 1,
        },
      ],
    },
  ],
  progress: { KR1: "passed", KR2: "running" },
  outcomes: {},

  constitution: { mission_statement: "Create practical tools with evidence." },
};
async function fixture(
  page: Page,
  overrides: Partial<Run> = {},
  files: Artifact[] = [
    {
      artifact_id: "artifact-1",
      name: "acceptance-results.txt",
      media_type: "text/plain",
      size: 1024,
      kr_id: "KR2",
    },
  ],
) {
  let run: Run = {
    ...initialRun,
    model_config: defaultSettings.defaults,
    ...overrides,
  };
  let settings = structuredClone(defaultSettings);
  let didReset = false;
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  await page.addInitScript(() => {
    const streams: EventSource[] = [];
    class FixtureSource extends EventTarget {
      url: string;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      constructor(url: string) {
        super();
        this.url = url;
        streams.push(this as unknown as EventSource);
        queueMicrotask(() => this.onopen?.(new Event("open")));
      }
      close() {}
    }
    Object.defineProperty(window, "EventSource", { value: FixtureSource });
    Object.assign(window, {
      __officeStreams: streams,
      __officeReset: () =>
        streams
          .at(-1)
          ?.dispatchEvent(new MessageEvent("reset", { data: "{}" })),
      __officeEmit: (data: unknown) => {
        streams
          .at(-1)
          ?.dispatchEvent(
            new MessageEvent("activity", { data: JSON.stringify(data) }),
          );
      },
    });
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (path === "/api/settings" && method === "GET")
      return route.fulfill({ json: settings });
    if (path === "/api/settings/model" && method === "PUT") {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
      settings = { ...settings, model_config: body };
      return route.fulfill({ json: settings });
    }
    if (path.startsWith("/api/settings/agents/")) {
      const agentId = decodeURIComponent(path.split("/").at(-1)!);
      const overrides = { ...settings.agent_model_configs };
      if (method === "PUT") {
        const body = route.request().postDataJSON();
        requests.push({ path, body });
        overrides[agentId] = body;
      } else if (method === "DELETE") {
        requests.push({ path, body: {} });
        delete overrides[agentId];
      }
      settings = { ...settings, agent_model_configs: overrides };
      return route.fulfill({ json: settings });
    }
    if (path === "/api/regenesis" && method === "POST") {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
      if (body.confirmation !== "REGENESIS")
        return route.fulfill({
          status: 422,
          json: { detail: "Type REGENESIS" },
        });
      didReset = true;
      settings = structuredClone(defaultSettings);
      return route.fulfill({
        json: { status: "reset", removed_runs: 1, settings },
      });
    }
    if (path === "/api/office" && didReset)
      return route.fulfill({
        json: { agents: [], cursor: 0, generation: "fixture-reset" },
      });
    if (path === "/api/office")
      return route.fulfill({
        json: {
          agents: [
            {
              event_id: "a10",
              seq: 10,
              source: "harness",
              agent_id: "backend_coder",
              activity: "executing",
              summary: "Running acceptance tests",
              run_id: runId,
              kr_id: "KR2",
              data: { tool_name: "run_command", stdout: "All tests passed" },
              timestamp: "2026-10-18T10:00:00Z",
            },
          ],
          cursor: 10,
          generation: "fixture-generation",
        },
      });
    if (path === "/api/runs" && method === "GET")
      return route.fulfill({ json: didReset ? [] : [run] });
    if (path === "/api/runs" && method === "POST") {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
      didReset = false;
      run = {
        ...run,
        user_request: body.user_request,
        status: "queued",
        model_config: body.model_config ?? settings.model_config,
      };
      return route.fulfill({
        status: 201,
        json: { run_id: runId, status: "queued" },
      });
    }
    if (path === `/api/runs/${runId}`) return route.fulfill({ json: run });
    if (path.endsWith("/artifacts")) return route.fulfill({ json: files });
    if (method === "POST") {
      const body = route.request().postDataJSON() ?? {};
      requests.push({ path, body });
      if (path.endsWith("/retry")) {
        run = { ...run, status: "queued", error: null };
        return route.fulfill({ status: 202, json: run });
      }
      if (path.endsWith("/pause")) run = { ...run, status: "paused" };
      if (path.endsWith("/resume")) run = { ...run, status: "running" };
      if (path.endsWith("/cancel")) run = { ...run, status: "cancelled" };
      return route.fulfill({ json: { status: run.status } });
    }
    return route.fulfill({
      status: 404,
      json: { detail: "Fixture route not found" },
    });
  });
  await page.goto("/");
  await expect(page.getByText("Office connected")).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue(runId);
  return requests;
}
test("projects live activity, isolates external identities, reconnects from cursor, and inspects evidence", async ({
  page,
}) => {
  await fixture(page);
  await expect(
    page.getByRole("dialog", { name: "Activity stream", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".office-footer")).toBeInViewport();
  await page
    .getByRole("button", { name: "Backend coder: Executing. Inspect agent" })
    .click();
  await expect(page.getByText("Running acceptance tests")).toBeVisible();
  await page.getByRole("tab", { name: "Files" }).click();
  await expect(
    page.getByRole("link", { name: /acceptance-results.txt/ }),
  ).toHaveAttribute("href", "/api/artifacts/artifact-1");
  await page.evaluate(() => {
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      event_id: "e11",
      seq: 11,
      source: "custom",
      agent_id: "backend_coder",
      activity: "reading",
      summary: "Reading integration notes",
      timestamp: "2026-10-18T10:00:02Z",
    });
  });
  await expect(
    page.getByRole("button", { name: "Backend Coder: Reading. Inspect agent" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Backend coder: Executing. Inspect agent",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Open activity stream" }).click();
  const activity = page.getByRole("dialog", {
    name: "Activity stream",
    exact: true,
  });
  await expect(
    activity.getByRole("heading", { name: "Recent activity 1" }),
  ).toBeVisible();
  await activity
    .locator(".timeline > button")
    .filter({ hasText: "Reading integration notes" })
    .click();
  await expect(activity).toBeHidden();
  await expect(
    page.getByRole("heading", { name: "Backend Coder", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Reading integration notes", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() => {
    const stream = (
      window as unknown as { __officeStreams: EventSource[] }
    ).__officeStreams.at(-1)!;
    stream.onerror?.(new Event("error"));
  });
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as unknown as { __officeStreams: EventSource[] }
          ).__officeStreams.at(-1)?.url,
      ),
    )
    .toContain("after=11");
  await page.screenshot({
    path: "test-results/office-desktop.png",
    fullPage: true,
  });
});
test("creates a mission with constitution and sends targeted guidance", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.getByRole("button", { name: "New mission" }).click();
  await page
    .getByLabel("What should the organization accomplish?")
    .fill("Build an evidence-backed planning API");
  await page.getByText("Constitution & boundaries").click();
  await page.getByLabel("Prohibited actions").fill("Delete unrelated files");
  await page.getByRole("button", { name: "Launch mission" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  expect(requests.find((r) => r.path === "/api/runs")?.body).toMatchObject({
    user_request: "Build an evidence-backed planning API",
    constitution: { prohibited_actions: ["Delete unrelated files"] },
  });
  await page
    .getByLabel("Send guidance", { exact: true })
    .fill("Prefer a minimal Python interface");
  await page.getByRole("button", { name: "Send guidance to agent" }).click();
  await expect(
    page.getByText("Guidance queued for the next agent boundary."),
  ).toBeVisible();
  expect(requests.at(-1)?.body).toMatchObject({
    agent_id: "executive",
    content: "Prefer a minimal Python interface",
  });
});
test("terminal runs stop working while external activity and historical evidence remain available", async ({
  page,
}) => {
  await fixture(page, { status: "succeeded" });
  await expect(page.locator(".office-metrics")).toContainText("0 working");
  await page
    .getByRole("button", { name: "Backend coder: Completed. Inspect agent" })
    .click();
  await expect(
    page.getByText(
      "Run succeeded. Last recorded activity: Executing — Running acceptance tests",
    ),
  ).toBeVisible();
  await page.evaluate(() => {
    const emit = (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit;
    emit({
      event_id: "historical-research",
      seq: 11,
      source: "harness",
      agent_id: "research_head",
      activity: "planning",
      summary: "Preparing a source comparison",
      run_id: "run-fixture",
      data: { output: "Recorded source comparison" },
      timestamp: "2026-10-18T10:00:02Z",
    });
    emit({
      event_id: "external-research",
      seq: 12,
      source: "custom-office",
      agent_id: "research_head",
      activity: "reading",
      summary: "Reading an independent integration feed",
      run_id: "run-fixture",
      timestamp: "2026-10-18T10:00:03Z",
    });
  });
  await expect(page.locator(".office-metrics")).toContainText("1 working");
  await expect(
    page.getByRole("button", { name: "Research Head: Reading. Inspect agent" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Research lead: Completed. Inspect agent" })
    .click();
  await expect(page.getByText("Recorded source comparison")).toBeVisible();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(
    page.getByRole("tabpanel").getByText("Planning", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("tabpanel").getByText("Preparing a source comparison", {
      exact: true,
    }),
  ).toBeVisible();
});
test("a failed mission explains its error and retries the same saved run", async ({
  page,
}) => {
  const requests = await fixture(page, {
    status: "failed",
    error: "Execution failed (NotFoundError)",
  });
  const banner = page.getByRole("alert");
  await expect(
    banner.getByText("Mission failed", { exact: true }),
  ).toBeVisible();
  await expect(
    banner.getByText("Execution failed (NotFoundError)"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Pause mission", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Review and resume mission" }),
  ).toBeDisabled();
  await expect(banner).toContainText(
    "Continue from saved work. Interrupted commands may require review.",
  );
  await banner
    .getByRole("button", { name: "Retry mission", exact: true })
    .click();
  await expect(banner).toBeHidden();
  await expect(page.locator(".run-controls")).toContainText("Queued");
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue(runId);
  expect(requests.filter((request) => request.path.endsWith("/retry"))).toEqual(
    [{ path: `/api/runs/${runId}/retry`, body: {} }],
  );
  expect(requests.some((request) => request.path === "/api/runs")).toBe(false);
});
test("an engineering fast track shows one worker and leaves Research idle", async ({
  page,
}) => {
  await fixture(page, {
    triage: {
      mode: "FAST_TRACK",
      departments: ["engineering"],
      reason: "One local engineering change is needed.",
    },
  });
  await expect(page.locator(".office-metrics")).toContainText("1 working");
  await expect(
    page.getByRole("button", { name: "Research lead: Idle. Inspect agent" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Market researcher: Idle. Inspect agent",
    }),
  ).toBeVisible();
  await expect(page.locator(".sidebar-note").first()).toHaveText(
    "Engineering only · One worker",
  );
  await expect(page.locator(".sidebar-note").first()).not.toContainText(
    "Research",
  );
});
test("a rejected retry stays visible and its error clears after a successful retry", async ({
  page,
}) => {
  await fixture(page, {
    status: "failed",
    error: "Execution failed (NotFoundError)",
  });
  let attempts = 0;
  await page.route(`**/api/runs/${runId}/retry`, (route) => {
    attempts++;
    return attempts === 1
      ? route.fulfill({
          status: 409,
          json: { detail: "Another operation is still finishing." },
        })
      : route.fallback();
  });
  await page
    .getByRole("button", { name: "Retry mission", exact: true })
    .click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Another operation is still finishing." }),
  ).toBeVisible();
  await expect(page.locator(".failure-banner")).toContainText(
    "Execution failed (NotFoundError)",
  );
  await page
    .getByRole("button", { name: "Retry mission", exact: true })
    .click();
  await expect(page.locator(".run-controls")).toContainText("Queued");
  await expect(page.getByRole("alert")).toHaveCount(0);
});
for (const status of ["succeeded", "cancelled"]) {
  test(`a ${status} mission does not offer recovery actions`, async ({
    page,
  }) => {
    const requests = await fixture(page, {
      status,
      error: "Historical failure",
    });
    await expect(
      page.getByRole("button", { name: "Retry mission", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Review and resume mission" }),
    ).toBeDisabled();
    expect(requests).toHaveLength(0);
  });
}
test("file-list failures do not hide updated run status and clear after recovery", async ({
  page,
}) => {
  await fixture(page, {
    status: "failed",
    error: "Execution failed (NotFoundError)",
  });
  await page.route(`**/api/runs/${runId}/artifacts`, (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "Artifact store temporarily unavailable." },
    }),
  );
  await page
    .getByRole("button", { name: "Retry mission", exact: true })
    .click();
  await expect(page.locator(".run-controls")).toContainText("Queued");
  await expect(page.locator(".failure-banner")).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveText(
    "Could not load files: Artifact store temporarily unavailable.",
  );
  await page.unroute(`**/api/runs/${runId}/artifacts`);
  await page.evaluate(() => {
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      event_id: "refresh-recovered-files",
      seq: 11,
      source: "harness",
      agent_id: "planner",
      activity: "completed",
      run_id: "run-fixture",
      summary: "Refresh saved state",
      timestamp: "2026-10-18T10:00:02Z",
    });
  });
  await expect(page.getByRole("alert")).toHaveCount(0);
});
test("missing artifact downloads show an inline error and can be downloaded after recovery", async ({
  page,
}) => {
  await fixture(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/artifacts/artifact-1", (route) =>
    route.fulfill({
      status: 404,
      json: { detail: "Artifact content is unavailable" },
    }),
  );
  await page
    .getByRole("button", { name: "Backend coder: Executing. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Files" }).click();
  const file = page.getByRole("link", { name: /acceptance-results.txt/ });
  const pagesBefore = page.context().pages().length;
  await file.click();
  await expect(page.getByRole("alert")).toHaveText(
    "Could not download acceptance-results.txt: Artifact content is unavailable",
  );
  expect(page.context().pages()).toHaveLength(pagesBefore);
  await expect(
    page.getByRole("heading", { name: "The office." }),
  ).toBeVisible();
  await page.unroute("**/api/artifacts/artifact-1");
  await page.route("**/api/artifacts/artifact-1", (route) =>
    route.fulfill({
      body: "All tests passed",
      contentType: "text/plain",
    }),
  );
  const download = page.waitForEvent("download");
  await file.click();
  expect((await download).suggestedFilename()).toBe("acceptance-results.txt");
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(errors).toHaveLength(0);
});
test("settings HTTP failures stay visible without an unhandled promise or false saved notice", async ({
  page,
}) => {
  await fixture(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/settings/model", (route) =>
    route.fulfill({
      status: 502,
      body: "<html>Proxy unavailable</html>",
      contentType: "text/html",
    }),
  );
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("button", { name: "Save model settings", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toHaveText(
    "The harness could not complete this request (502).",
  );
  await expect(
    dialog.getByText("Saved. New missions will use this model."),
  ).toHaveCount(0);
  await expect(
    dialog.getByRole("button", { name: "Save model settings", exact: true }),
  ).toBeEnabled();
  expect(errors).toHaveLength(0);
});
test("an invalid office snapshot reports its failure without crashing the workspace", async ({
  page,
}) => {
  await fixture(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/office", (route) =>
    route.fulfill({ json: { agents: null, cursor: "invalid" } }),
  );
  await page.evaluate(() => {
    (window as unknown as { __officeStreams: EventSource[] }).__officeStreams
      .at(-1)
      ?.onerror?.(new Event("error"));
  });
  await expect(page.getByRole("status")).toContainText(
    "The harness returned an invalid office snapshot.",
  );
  await expect(
    page.getByRole("heading", { name: "The office." }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue(runId);
  expect(errors).toHaveLength(0);
});
test("pauses, resumes from a durable boundary, and cancels a run", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page
    .getByRole("button", { name: "Pause mission", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Review and resume mission" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Review and resume mission" }).click();
  await page.getByRole("button", { name: "Resume work", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  expect(requests.find((r) => r.path.endsWith("/resume"))?.body).toMatchObject({
    interrupt_id: "pause",
    action: "continue",
  });
  await page
    .getByRole("button", { name: "Cancel mission", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Pause mission", exact: true }),
  ).toBeDisabled();
});
test("offers usable mobile navigation and keyboard agent selection with reduced motion", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await fixture(page);
  await expect(
    page.getByRole("dialog", { name: "Activity stream", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Open activity stream" }).click();
  const activity = page.getByRole("dialog", {
    name: "Activity stream",
    exact: true,
  });
  await expect(
    activity.getByRole("heading", { name: "Recent activity 0" }),
  ).toBeVisible();
  await activity.getByRole("button", { name: "Close dialog" }).click();
  await expect(activity).toBeHidden();
  await page.getByRole("button", { name: "Agents", exact: true }).click();
  await page.getByRole("textbox", { name: "Search agents" }).fill("architect");
  await expect(
    page.getByRole("button", {
      name: /System architect Engineering specialist/,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /System architect Engineering specialist/ })
    .focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "System architect" }),
  ).toBeVisible();
  await page.locator(".mobile-strategy > summary").click();
  await expect(
    page.getByText("Build a useful planning tool").last(),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/office-mobile.png",
    fullPage: true,
  });
});

test("submits a versioned KR revision against the current human interrupt", async ({
  page,
}) => {
  const requests = await fixture(page, {
    status: "review",
    review: {
      interrupt_id: "interrupt-actual",
      kind: "blocker",
      message: "The engineering KR needs clarification.",
      kr_id: "KR2",
    },
  });
  await page.getByRole("button", { name: "Review and resume mission" }).click();
  await page.getByRole("radio", { name: /Change requirements/ }).check();
  await page
    .getByRole("combobox", { name: "Task to update", exact: true })
    .selectOption("KR2");
  await page.getByLabel("Updated task").fill("Build a tested local API");
  await page
    .getByLabel("Requirements, one per line")
    .fill("Unit tests pass\nAPI responds locally");
  await page
    .getByRole("button", { name: "Save changes and retry", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeHidden();
  expect(
    requests.find((request) => request.path.endsWith("/resume"))?.body,
  ).toMatchObject({
    interrupt_id: "interrupt-actual",
    action: "revise_kr",
    kr_id: "KR2",
    description: "Build a tested local API",
    acceptance_criteria: ["Unit tests pass", "API responds locally"],
  });
});

test("shows review evidence and separates failed work from waiting dependencies", async ({
  page,
}) => {
  await fixture(
    page,
    {
      status: "review",
      progress: { KR1: "escalated", KR2: "pending" },
      outcomes: {
        KR1: { escalation: { reason: "The worker produced no inventory." } },
      },
      review: {
        interrupt_id: "saved-interrupt",
        kind: "constitution_violation",
        reason: "The worker produced no inventory.",
        kr_ids: ["KR1", "KR2"],
        allowed_actions: ["provide_context", "revise_kr", "abort"],
        context: {
          mission: "Build a useful planning tool with cited evidence",
          blockers: [
            { kr_id: "KR1", reason: "The worker produced no inventory." },
          ],
          key_results: [
            {
              kr_id: "KR1",
              version: 1,
              epoch: 3,
              department: "research",
              description: "Research validated user needs",
              acceptance_criteria: ["Cite three sources"],
              status: "escalated",
              attempts: [
                {
                  attempt_id: "attempt-1",
                  stage: "worker",
                  work_package_id: "WP-inventory",
                  role: "market_researcher",
                  execution_attempt: 0,
                  epoch: 3,
                  summary: "No inventory was produced",
                  artifact_ids: [],
                  evidence: [],
                  evaluation: {
                    score: 0,
                    feedback: "Missing the inventory file",
                    criterion_results: { "Inventory exists": false },
                  },
                  approved: false,
                },
              ],
            },
          ],
          retry_summary: {
            automatic_replans_used: 1,
            automatic_replans_limit: 1,
            revision_limit: 2,
            attempts_recorded: 1,
          },
        },
      },
    },
    [
      {
        artifact_id: "raw",
        name: "web-reader.json",
        media_type: "application/json",
        kind: "research",
        size: 86000,
        kr_id: "KR1",
        epoch: 3,
      },
      {
        artifact_id: "metadata",
        name: "worker-deliverable.json",
        media_type: "application/json",
        kind: "deliverable",
        size: 270,
        kr_id: "KR1",
        epoch: 3,
      },
      {
        artifact_id: "stderr",
        name: "check.stderr.txt",
        media_type: "text/plain",
        kind: "command_log",
        size: 0,
        kr_id: "KR1",
        epoch: 3,
      },
    ],
  );
  await page.getByRole("button", { name: "Review and resume mission" }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog
      .locator(".review-mission-line")
      .getByText("Build a useful planning tool with cited evidence"),
  ).toBeVisible();
  await expect(
    dialog.getByRole("region", { name: "Review KR1", exact: true }),
  ).not.toBeVisible();
  await dialog
    .getByText("Review evidence and history", { exact: true })
    .click();
  await expect(
    dialog
      .locator(".review-details .review-blocker")
      .getByText("The worker produced no inventory.", { exact: true }),
  ).toBeVisible();
  const kr = dialog.getByRole("region", { name: "Review KR1", exact: true });
  await expect(
    kr.getByText("Cite three sources", { exact: true }),
  ).toBeVisible();
  await expect(
    kr.getByText("Missing the inventory file", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    kr.getByText("No inventory was produced", { exact: true }),
  ).toBeVisible();
  await expect(kr.getByText("0 task outputs", { exact: true })).toBeVisible();
  await expect(
    kr.getByRole("link", { name: /check.stderr.txt Empty log/ }),
  ).toHaveAttribute("href", "/api/artifacts/stderr");
  await expect(
    dialog.getByText("1 key result is waiting on dependencies"),
  ).toBeVisible();
  await expect(
    dialog.getByRole("region", { name: "Review KR2", exact: true }),
  ).toHaveCount(0);
  await expect(dialog.getByRole("radio", { name: /Resume work/ })).toHaveCount(
    0,
  );
  await expect(dialog.getByText("1 / 1", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "test-results/review-context-desktop.png",
    fullPage: true,
  });
});

test("ordinary source review offers a compact retry and preserves the exact feedback and interrupt", async ({
  page,
}) => {
  const reason = "The Reader tool failed; check its entitlement and quota.";
  const requests = await fixture(page, {
    status: "review",
    review: {
      interrupt_id: "reader-interrupt",
      kind: "missing_resource",
      reason,
      allowed_actions: ["provide_context", "revise_kr", "abort"],
      kr_ids: ["KR1"],
    },
  });
  await page.getByRole("button", { name: "Review and resume mission" }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("heading", { name: "How should the team continue?" }),
  ).toBeVisible();
  await expect(
    dialog.getByText(
      "A required source could not be read. Retry after access is restored, or add an alternative source.",
    ),
  ).toBeVisible();
  await expect(dialog.getByRole("radio")).toHaveCount(2);
  await expect(
    dialog.getByRole("region", { name: "Review KR1", exact: true }),
  ).not.toBeVisible();
  const button = dialog.getByRole("button", {
    name: "Retry task",
    exact: true,
  });
  await expect(button).toBeInViewport({ ratio: 1 });
  await dialog
    .getByText("Add instructions or an alternative source", { exact: true })
    .click();
  await dialog
    .getByLabel("Instructions or source URL")
    .fill("Use https://example.org/source as an alternative source.");
  await button.click();
  await expect(page.getByRole("dialog")).toBeHidden();
  const body = requests.find((request) =>
    request.path.endsWith("/resume"),
  )?.body;
  expect(body).toMatchObject({
    interrupt_id: "reader-interrupt",
    action: "provide_context",
  });
  expect(body?.context).toContain(
    "Try the blocked work again using the current requirements and recorded feedback.",
  );
  expect(body?.context).toContain(`Recorded review feedback:\n${reason}`);
  expect(body?.context).toContain(
    "Additional instructions:\nUse https://example.org/source as an alternative source.",
  );
});
test("worker timeout review explains the deadline and does not recommend a blind retry", async ({
  page,
}) => {
  const reason =
    "backend_coder exceeded its 60-second work limit before finishing.";
  const requests = await fixture(page, {
    status: "review",
    review: {
      interrupt_id: "timeout-interrupt",
      kind: "blocked",
      reason,
      allowed_actions: ["provide_context", "revise_kr", "abort"],
    },
  });
  await page.getByRole("button", { name: "Review and resume mission" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".review-brief")).toContainText(
    "The worker reached its time limit before finishing.",
  );
  await expect(dialog.locator(".review-brief")).toContainText(reason);
  await expect(dialog.locator(".review-brief")).toContainText(
    "Retry can reuse saved sources; the per-worker limit and run allowance stay unchanged.",
  );
  await expect(dialog.getByText("Recommended", { exact: true })).toHaveCount(0);
  await expect(
    dialog.getByRole("button", { name: "Retry task", exact: true }),
  ).toBeEnabled();
  expect(requests).toHaveLength(0);
});
test("policy review requires written guidance and keeps its action visible on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page, {
    status: "review",
    review: {
      interrupt_id: "policy-interrupt",
      kind: "constitution_violation",
      reason: "A worker tried to delete protected files.",
      allowed_actions: ["provide_context", "revise_kr", "abort"],
    },
  });
  await page.getByRole("button", { name: "Review and resume mission" }).click();
  const dialog = page.getByRole("dialog");
  const button = dialog.getByRole("button", {
    name: "Send guidance and retry",
    exact: true,
  });
  await expect(button).toBeDisabled();
  await dialog
    .getByLabel("What should the team do differently?")
    .fill("Use a separate folder and preserve protected files.");
  await expect(button).toBeEnabled();
  await expect(button).toBeInViewport({ ratio: 1 });
  expect((await button.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  expect(
    (
      await dialog
        .getByRole("button", { name: "Stop run", exact: true })
        .boundingBox()
    )?.height ?? 0,
  ).toBeGreaterThanOrEqual(44);
  expect(
    await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/review-compact-mobile.png",
    fullPage: true,
  });
});

test("saves configured provider choices and snapshots model selection into new missions", async ({
  page,
}) => {
  const requests = await fixture(page, {
    model_config: defaultSettings.defaults,
    triage: {
      mode: "DEPARTMENTAL",
      departments: ["engineering"],
      reason: "Only a local code change is needed.",
    },
  });
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("option", {
      name: "OpenAI · Not configured",
      exact: true,
    }),
  ).toHaveJSProperty("disabled", true);
  await dialog
    .getByRole("combobox", { name: "Provider", exact: true })
    .selectOption("zai");
  await dialog
    .getByRole("textbox", { name: "Model", exact: true })
    .fill("custom-glm-model");
  await dialog
    .getByRole("combobox", { name: "Reasoning", exact: true })
    .selectOption("high");
  await page.screenshot({
    path: "test-results/model-settings.png",
    fullPage: true,
  });
  await dialog
    .getByRole("button", { name: "Save model settings", exact: true })
    .click();
  await expect(
    dialog.getByText("Saved. New missions will use this model."),
  ).toBeVisible();
  expect(
    requests.find((request) => request.path === "/api/settings/model")?.body,
  ).toEqual({
    provider: "zai",
    model: "custom-glm-model",
    reasoning_effort: "high",
  });
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  await page.locator(".run-configuration>summary").click();
  await expect(
    page.getByText("Model snapshot: configured / glm-5.3-flash · max"),
  ).toBeVisible();
  await expect(
    page.getByText("Only a local code change is needed."),
  ).toBeVisible();
  await page.getByRole("button", { name: "New mission", exact: true }).click();
  await expect(
    page.getByRole("dialog").getByText("custom-glm-model", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("What should the organization accomplish?")
    .fill("Build one well-tested local script");
  await page
    .getByRole("button", { name: "Launch mission", exact: true })
    .click();
  expect(
    requests.find((request) => request.path === "/api/runs")?.body.model_config,
  ).toEqual({
    provider: "zai",
    model: "custom-glm-model",
    reasoning_effort: "high",
  });
});
test("Regenesis requires exact typed confirmation and resets the client from a fresh stream snapshot", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.evaluate(() => {
    (
      window as unknown as { __officeEmit: (value: unknown) => void }
    ).__officeEmit({
      event_id: "before-reset",
      seq: 11,
      source: "custom",
      agent_id: "old-agent",
      activity: "writing",
      summary: "Old activity before reset",
      timestamp: "2026-10-18T10:00:02Z",
    });
  });
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: "Regenesis", exact: true }).click();
  const reset = dialog.getByRole("button", {
    name: "Reset all harness data",
    exact: true,
  });
  await expect(reset).toBeDisabled();
  await expect(
    dialog.getByText(/External workspaces you selected are kept/),
  ).toBeVisible();
  await dialog.getByLabel("Type REGENESIS to confirm").fill("regenesis");
  await expect(reset).toBeDisabled();
  expect(requests.some((request) => request.path === "/api/regenesis")).toBe(
    false,
  );
  await page.screenshot({
    path: "test-results/regenesis-confirmation.png",
    fullPage: true,
  });
  await dialog.getByLabel("Type REGENESIS to confirm").fill("REGENESIS");
  await reset.click();
  await expect(
    dialog.getByText(/Regenesis complete. 1 run was removed/),
  ).toBeVisible();
  expect(
    requests.find((request) => request.path === "/api/regenesis")?.body,
  ).toEqual({ confirmation: "REGENESIS" });
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Executive: Idle. Inspect agent" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Old Agent/ })).toHaveCount(0);
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as unknown as { __officeStreams: EventSource[] }
          ).__officeStreams.at(-1)?.url,
      ),
    )
    .toContain("after=0");
  await page.getByRole("button", { name: "Open activity stream" }).click();
  await expect(
    page
      .getByRole("dialog", { name: "Activity stream", exact: true })
      .getByRole("heading", { name: "Recent activity 0" }),
  ).toBeVisible();
});
test("another client reset event clears stale run data and reopens the stream at zero", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.route("**/api/office", (route) =>
    route.fulfill({ json: { agents: [], cursor: 0 } }),
  );
  await page.route("**/api/runs", (route) => route.fulfill({ json: [] }));
  await page.getByRole("button", { name: "Open activity stream" }).click();
  const activity = page.getByRole("dialog", {
    name: "Activity stream",
    exact: true,
  });
  await expect(activity).toBeVisible();
  await page.evaluate(() => {
    (window as unknown as { __officeReset: () => void }).__officeReset();
  });
  await expect(activity).toBeHidden();
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Backend coder: Idle. Inspect agent" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as unknown as { __officeStreams: EventSource[] }
          ).__officeStreams.at(-1)?.url,
      ),
    )
    .toContain("after=0");
  await page.getByRole("button", { name: "Open activity stream" }).click();
  await expect(
    activity.getByRole("heading", { name: "Recent activity 0" }),
  ).toBeVisible();
  expect(requests.some((request) => request.path === "/api/regenesis")).toBe(
    false,
  );
});

test("same-generation reconnect replays missed activity from the last received sequence", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/office", (route) =>
    route.fulfill({
      json: {
        agents: [
          {
            event_id: "persisted-12",
            seq: 12,
            source: "harness",
            agent_id: "backend_coder",
            activity: "writing",
            summary: "Writing the final acceptance report",
            run_id: runId,
            timestamp: "2026-10-18T10:00:04Z",
          },
        ],
        cursor: 12,
        generation: "fixture-generation",
      },
    }),
  );
  await page.evaluate(() => {
    (window as unknown as { __officeStreams: EventSource[] }).__officeStreams
      .at(-1)
      ?.onerror?.(new Event("error"));
  });
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as unknown as { __officeStreams: EventSource[] })
            .__officeStreams.length,
      ),
    )
    .toBe(2);
  expect(
    await page.evaluate(
      () =>
        (
          window as unknown as { __officeStreams: EventSource[] }
        ).__officeStreams.at(-1)?.url,
    ),
  ).toBe("/api/events?after=10&generation=fixture-generation");
  await page.evaluate(() => {
    const emit = (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit;
    for (const seq of [11, 12])
      emit({
        event_id: `persisted-${seq}`,
        seq,
        source: "harness",
        agent_id: "backend_coder",
        activity: seq === 11 ? "reading" : "writing",
        summary:
          seq === 11
            ? "Read acceptance results while disconnected"
            : "Writing the final acceptance report",
        run_id: "run-fixture",
        timestamp: `2026-10-18T10:00:0${seq - 8}Z`,
      });
  });
  await page.getByRole("button", { name: "Open activity stream" }).click();
  const activity = page.getByRole("dialog", {
    name: "Activity stream",
    exact: true,
  });
  await expect(
    activity.getByText("Read acceptance results while disconnected"),
  ).toBeVisible();
  await expect(
    activity.getByText("Writing the final acceptance report"),
  ).toBeVisible();
  await expect(
    activity.getByRole("heading", { name: "Recent activity 2" }),
  ).toBeVisible();
  await activity.getByRole("button", { name: "Close dialog" }).click();
  await expect(
    page.getByRole("button", { name: "Backend coder: Writing. Inspect agent" }),
  ).toBeVisible();
});
test("reconnecting after an offline reset replaces stale missions and accepts the new generation’s first event", async ({
  page,
}) => {
  await fixture(page);
  await page.evaluate(() => {
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      event_id: "offline-old-event",
      seq: 11,
      source: "custom-office",
      agent_id: "old-agent",
      activity: "writing",
      summary: "Old generation activity",
      timestamp: "2026-10-18T10:00:02Z",
    });
  });
  await page.getByRole("button", { name: "Open activity stream" }).click();
  const activity = page.getByRole("dialog", {
    name: "Activity stream",
    exact: true,
  });
  await expect(activity.getByText("Old generation activity")).toBeVisible();
  await page.route("**/api/office", (route) =>
    route.fulfill({
      json: { agents: [], cursor: 0, generation: "after-offline-reset" },
    }),
  );
  await page.route("**/api/runs", (route) => route.fulfill({ json: [] }));
  let reloadedSettings = false;
  await page.route("**/api/settings", (route) => {
    reloadedSettings = true;
    return route.fulfill({ json: defaultSettings });
  });
  await page.evaluate(() => {
    const streams = (window as unknown as { __officeStreams: EventSource[] })
      .__officeStreams;
    streams.at(-1)?.onerror?.(new Event("error"));
  });
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as unknown as { __officeStreams: EventSource[] }
          ).__officeStreams.at(-1)?.url,
      ),
    )
    .toBe("/api/events?after=0&generation=after-offline-reset");
  await expect(activity).toBeHidden();
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue("");
  await expect(page.getByText("Old generation activity")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Old Agent/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Open activity stream" }).click();
  await expect(
    activity.getByRole("heading", { name: "Recent activity 0" }),
  ).toBeVisible();
  expect(reloadedSettings).toBe(true);
  await page.evaluate(() => {
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      event_id: "new-generation-first-event",
      seq: 1,
      source: "custom-office",
      agent_id: "new-agent",
      activity: "reading",
      summary: "First activity after offline reset",
      timestamp: "2026-10-18T10:01:00Z",
    });
  });
  await expect(
    activity.getByText("First activity after offline reset"),
  ).toBeVisible();
  await expect(
    activity.getByRole("heading", { name: "Recent activity 1" }),
  ).toBeVisible();
  await activity.getByRole("button", { name: "Close dialog" }).click();
  await expect(
    page.getByRole("button", { name: "New Agent: Reading. Inspect agent" }),
  ).toBeVisible();
});
test("a regressed snapshot also detects a reset when the generation token is unavailable", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/office", (route) =>
    route.fulfill({ json: { agents: [], cursor: 0 } }),
  );
  await page.route("**/api/runs", (route) => route.fulfill({ json: [] }));
  await page.evaluate(() => {
    (window as unknown as { __officeStreams: EventSource[] }).__officeStreams
      .at(-1)
      ?.onerror?.(new Event("error"));
  });
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as unknown as { __officeStreams: EventSource[] }
          ).__officeStreams.at(-1)?.url,
      ),
    )
    .toBe("/api/events?after=0");
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Backend coder: Idle. Inspect agent" }),
  ).toBeVisible();
});
test("per-agent model overrides can be saved and returned to the inherited default", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("combobox", { name: "Apply to", exact: true })
    .selectOption("system_architect");
  await expect(
    dialog.getByText(/This agent inherits the default model/),
  ).toBeVisible();
  await dialog
    .getByRole("textbox", { name: "Model", exact: true })
    .fill("architect-model");
  await dialog
    .getByRole("combobox", { name: "Reasoning", exact: true })
    .selectOption("high");
  await dialog
    .getByRole("button", { name: "Save agent model", exact: true })
    .click();
  await expect(
    dialog.getByRole("button", { name: "Use default model", exact: true }),
  ).toBeVisible();
  expect(
    requests.find(
      (request) => request.path === "/api/settings/agents/system_architect",
    )?.body,
  ).toEqual({
    provider: "configured",
    model: "architect-model",
    reasoning_effort: "high",
  });
  await dialog
    .getByRole("combobox", { name: "Apply to", exact: true })
    .selectOption("all");
  await expect(
    dialog.getByRole("textbox", { name: "Model", exact: true }),
  ).toHaveValue("glm-5.3-flash");
  await dialog
    .getByRole("combobox", { name: "Apply to", exact: true })
    .selectOption("system_architect");
  await dialog
    .getByRole("button", { name: "Use default model", exact: true })
    .click();
  await expect(
    dialog.getByText("The agent now inherits the default model.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    dialog.getByRole("textbox", { name: "Model", exact: true }),
  ).toHaveValue("glm-5.3-flash");
});

test("a rejected Regenesis leaves existing mission data intact", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/regenesis", (route) =>
    route.fulfill({
      status: 409,
      json: {
        detail: "Workers are still stopping. Try again after they stop.",
      },
    }),
  );
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: "Regenesis", exact: true }).click();
  await dialog.getByLabel("Type REGENESIS to confirm").fill("REGENESIS");
  await dialog
    .getByRole("button", { name: "Reset all harness data", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toHaveText(
    "Workers are still stopping. Try again after they stop.",
  );
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue(runId);
  await expect(
    page.getByRole("button", {
      name: "Backend coder: Executing. Inspect agent",
    }),
  ).toBeVisible();
});

test("named Engineering specialists page separately from external integrations and preserve actual identity", async ({
  page,
}) => {
  const requests = await fixture(page, {
    agent_model_configs: {
      backend_coder: {
        provider: "zai",
        model: "shader-model",
        reasoning_effort: "high",
      },
    },
  });
  await page.evaluate(() => {
    const emit = (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit;
    for (let index = 1; index <= 8; index++)
      emit({
        event_id: `specialist-${index}`,
        seq: 10 + index,
        source: "harness",
        agent_id: `specialist:run-fixture:${String(index).padStart(16, "0")}`,
        run_id: "run-fixture",
        activity: "writing",
        summary: `Implementing shader part ${index}`,
        data: {
          agent_type: "engineering_specialist",
          display_name: `Shader specialist ${index}`,
          parent_agent_id: "engineering_head",
          department: "engineering",
          model_parent: "backend_coder",
        },
        timestamp: "2026-10-18T10:00:02Z",
      });
    emit({
      event_id: "external-specialist",
      seq: 19,
      source: "custom-office",
      agent_id: "specialist:run-fixture:0000000000000001",
      run_id: "run-fixture",
      activity: "reading",
      summary: "Watching an external feed",
      data: {
        agent_type: "engineering_specialist",
        display_name: "External shader monitor",
        parent_agent_id: "engineering_head",
        department: "engineering",
        model_parent: "backend_coder",
      },
      timestamp: "2026-10-18T10:00:03Z",
    });
  });
  await expect(
    page.getByText("Engineering specialists 1–4 of 8", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Shader specialist 1: Writing. Inspect agent",
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Shader specialist 8: Writing. Inspect agent",
    }),
  ).toHaveCount(0);
  await page
    .getByRole("button", {
      name: "Next Engineering specialists page",
      exact: true,
    })
    .click();
  await expect(
    page.getByText("Engineering specialists 5–8 of 8", { exact: true }),
  ).toBeVisible();
  const specialist = page.getByRole("button", {
    name: "Shader specialist 8: Writing. Inspect agent",
  });
  await specialist.click();
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(
    inspector.getByRole("heading", {
      name: "Shader specialist 8",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    inspector.locator(".detail-row").filter({ hasText: "Department" }),
  ).toContainText("Engineering");
  await expect(
    inspector.locator(".detail-row").filter({ hasText: "Parent" }),
  ).toContainText("Engineering lead");
  await expect(inspector.locator(".agent-model-note")).toContainText(
    "zai / shader-model · high",
  );
  await expect(inspector.locator(".agent-model-note")).toContainText(
    "Inherited from Backend coder",
  );
  const canvas = await page.locator(".office-canvas canvas").boundingBox();
  const hitbox = await specialist.boundingBox();
  expect(canvas).not.toBeNull();
  expect(hitbox).not.toBeNull();
  expect(
    (hitbox!.x + hitbox!.width / 2 - canvas!.x) / canvas!.width,
  ).toBeCloseTo(0.94, 2);
  expect(
    (hitbox!.y + hitbox!.height / 2 - canvas!.y) / canvas!.height,
  ).toBeCloseTo(575 / 650, 2);
  await page
    .getByLabel("Send guidance", { exact: true })
    .fill("Reuse the saved shader sources.");
  await page.getByRole("button", { name: "Send guidance to agent" }).click();
  await expect(
    page.getByText("Guidance queued for the next agent boundary."),
  ).toBeVisible();
  expect(
    requests.find((request) => request.path.endsWith("/notes"))?.body,
  ).toMatchObject({
    agent_id: "specialist:run-fixture:0000000000000008",
    content: "Reuse the saved shader sources.",
  });
  await page
    .getByRole("button", {
      name: "External shader monitor: Reading. Inspect agent",
    })
    .click();
  await expect(
    inspector.locator(".detail-row").filter({ hasText: "Department" }),
  ).toContainText("Integrations");
  await expect(inspector.locator(".agent-model-note")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Send guidance to agent" }),
  ).toBeDisabled();
  await page.evaluate(() => {
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      event_id: "specialist-status",
      seq: 20,
      source: "harness",
      agent_id: "specialist:run-fixture:0000000000000008",
      run_id: "run-fixture",
      activity: "reading",
      summary: "Checking shader validation",
      data: { tool_name: "compile" },
      timestamp: "2026-10-18T10:00:04Z",
    });
  });
  await page.getByRole("button", { name: "Open activity stream" }).click();
  const row = page
    .getByRole("dialog")
    .locator(".timeline > button")
    .filter({ hasText: "Checking shader validation" });
  await expect(row).toContainText("Shader specialist 8");
  await row.click();
  await expect(
    page.getByRole("button", {
      name: "Shader specialist 8: Reading. Inspect agent",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Agents", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search agents" })
    .fill("Shader specialist");
  await expect(page.locator(".agent-list .agent-row")).toHaveCount(8);
  await page
    .locator(".agent-list .agent-row")
    .filter({ hasText: "Shader specialist 1" })
    .click();
  await page.getByRole("button", { name: "Office", exact: true }).click();
  await expect(
    page.getByRole("button", {
      name: "Shader specialist 1: Writing. Inspect agent",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Engineering specialists 1–4 of 8", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/engineering-specialists.png",
    fullPage: true,
  });
});

test("Tools R&D stays caller-controlled while its fixed model setting is configurable", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page
    .getByRole("button", { name: "Tools R&D lead: Idle. Inspect agent" })
    .click();
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(inspector.locator(".agent-access-note")).toHaveText(
    "Only Planner or Engineering lead may call this agent.",
  );
  await expect(
    page.getByRole("button", { name: "Send guidance to agent" }),
  ).toBeDisabled();
  await page.getByRole("tab", { name: "Files" }).click();
  await expect(inspector.getByRole("link")).toHaveCount(0);
  await expect(
    inspector.getByText("0 task outputs", { exact: true }),
  ).toBeVisible();
  await expect(
    inspector.getByRole("tab", { name: "Files", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("combobox", { name: "Apply to", exact: true })
    .selectOption("tools_rd_lead");
  await expect(dialog.locator(".agent-access-note")).toHaveText(
    "Only Planner or Engineering lead may call this agent.",
  );
  await dialog
    .getByRole("textbox", { name: "Model", exact: true })
    .fill("tools-research-model");
  await dialog
    .getByRole("combobox", { name: "Reasoning", exact: true })
    .selectOption("high");
  await dialog
    .getByRole("button", { name: "Save agent model", exact: true })
    .click();
  await expect(dialog.getByRole("status")).toContainText("Tools R&D lead");
  expect(
    requests.find(
      (request) => request.path === "/api/settings/agents/tools_rd_lead",
    )?.body,
  ).toEqual({
    provider: "configured",
    model: "tools-research-model",
    reasoning_effort: "high",
  });
  await expect(
    dialog.getByRole("option", { name: /Shader specialist/ }),
  ).toHaveCount(0);
});

test("agent file scopes isolate same-KR authors and label legacy worker context", async ({
  page,
}) => {
  const alpha = "specialist:run-fixture:aaaaaaaaaaaaaaaa";
  const beta = "specialist:run-fixture:bbbbbbbbbbbbbbbb";
  const file = (
    id: string,
    actor?: string,
    extras: Partial<Artifact> = {},
  ): Artifact => ({
    artifact_id: id,
    name: `${id}.json`,
    media_type: "application/json",
    run_id: runId,
    kr_id: "KR2",
    size: 128,
    ...(actor ? { scope: JSON.stringify([`work-${id}`, 0, actor]) } : {}),
    ...extras,
  });
  await fixture(page, {}, [
    file("alpha-output", alpha),
    file("beta-output", beta),
    file("malformed-claim", undefined, {
      scope: JSON.stringify(["work", "0", alpha]),
    }),
    file("legacy-context"),
    file("mission-wide", undefined, { kr_id: undefined }),
    file("backend-own", "backend_coder"),
    file("foreign-run", alpha, { run_id: "other-run" }),
  ]);
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await page
    .getByRole("button", { name: "System architect: Idle. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Files" }).click();
  await expect(inspector.getByRole("link")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Backend coder: Executing. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Files" }).click();
  await expect(
    inspector
      .getByRole("region", { name: "Created by this agent", exact: true })
      .getByRole("link", { name: /backend-own.json/ }),
  ).toBeVisible();
  await expect(
    inspector
      .getByRole("region", {
        name: "Legacy key result context · author not recorded",
        exact: true,
      })
      .getByRole("link", { name: /legacy-context.json/ }),
  ).toBeVisible();
  await expect(inspector.getByRole("link")).toHaveCount(2);
  await page.evaluate(
    ({ alpha, beta }) => {
      const emit = (
        window as unknown as { __officeEmit: (event: unknown) => void }
      ).__officeEmit;
      for (const [index, id, name] of [
        [11, alpha, "Alpha specialist"],
        [12, beta, "Beta specialist"],
      ] as const)
        emit({
          event_id: `scoped-${index}`,
          seq: index,
          source: "harness",
          agent_id: id,
          run_id: "run-fixture",
          kr_id: "KR2",
          activity: "writing",
          summary: "Writing scoped output",
          data: {
            agent_type: "engineering_specialist",
            display_name: name,
            parent_agent_id: "engineering_head",
            model_parent: "backend_coder",
          },
          timestamp: "2026-10-18T10:00:02Z",
        });
    },
    { alpha, beta },
  );
  for (const [name, artifact] of [
    ["Alpha specialist", "alpha-output.json"],
    ["Beta specialist", "beta-output.json"],
  ]) {
    await page
      .getByRole("button", {
        name: `${name}: Writing. Inspect agent`,
        exact: true,
      })
      .click();
    await page.getByRole("tab", { name: "Files" }).click();
    await expect(inspector.getByRole("link")).toHaveCount(1);
    await expect(
      inspector
        .getByRole("region", { name: "Created by this agent", exact: true })
        .getByRole("link", { name: new RegExp(artifact) }),
    ).toBeVisible();
    await expect(inspector.getByText(/Legacy key result context/)).toHaveCount(
      0,
    );
    await expect(
      inspector.getByRole("link", {
        name: /malformed-claim|foreign-run|mission-wide/,
      }),
    ).toHaveCount(0);
  }
});
