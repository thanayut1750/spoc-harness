import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import type {
  ActivityEvent,
  Artifact,
  Run,
  WorkspaceSettings,
} from "../src/types";
const runId = "run-fixture";
function eventBubble(page: Page, agentKey: string) {
  return page.locator(
    `.agent-event-bubble[data-agent-key=${JSON.stringify(agentKey)}]`,
  );
}
function summaryBubble(page: Page, summary: string) {
  return page.locator(".agent-event-bubble").filter({ hasText: summary });
}

test("independent Tools R&D task actors keep private files, activity, and inherited models", async ({
  page,
}) => {
  const alpha = "specialist:run-fixture:rd-alpha";
  const beta = "specialist:run-fixture:rd-beta";
  await fixture(
    page,
    {
      agent_model_configs: {
        tools_rd_lead: {
          provider: "zai",
          model: "rd-private-model",
          reasoning_effort: "high",
        },
      },
    },
    [
      {
        artifact_id: "rd-alpha",
        name: "alpha-report.md",
        media_type: "text/plain",
        run_id: runId,
        kr_id: "KR2",
        scope: JSON.stringify(["rd-job-alpha", 0, alpha]),
        size: 300,
      },
      {
        artifact_id: "rd-beta",
        name: "beta-tool.py",
        media_type: "text/plain",
        run_id: runId,
        kr_id: "KR2",
        scope: JSON.stringify(["rd-job-beta", 0, beta]),
        size: 400,
      },
      {
        artifact_id: "legacy-rd",
        name: "legacy-role-report.md",
        media_type: "text/plain",
        run_id: runId,
        kr_id: "KR2",
        scope: JSON.stringify(["legacy-job", 0, "tools_rd_lead"]),
        size: 200,
      },
    ],
  );
  await page.evaluate(() => {
    const emit = (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit;
    for (const [index, id, name, parent] of [
      [
        0,
        "specialist:run-fixture:rd-alpha",
        "Source adapter research",
        "planner",
      ],
      [
        1,
        "specialist:run-fixture:rd-beta",
        "Parser tool build",
        "engineering_head",
      ],
      [2, "specialist:run-fixture:rd-alpha", "External R&D mirror", "planner"],
    ] as const)
      emit({
        event_id: `rd-task-${index}`,
        seq: 70 + index,
        source: index === 2 ? "external-rd" : "harness",
        agent_id: id,
        run_id: "run-fixture",
        kr_id: "KR2",
        activity: "writing",
        summary: `Saved private R&D evidence ${index}`,
        data: {
          agent_type: "tools_rd_task",
          display_name: name,
          parent_agent_id: parent,
          department: "engineering",
          model_parent: "tools_rd_lead",
          base_role: "tools_rd_lead",
        },
        timestamp: "2026-10-21T10:00:00Z",
      });
  });
  await expect(
    page.getByText("Task specialists 1–2 of 2", { exact: true }),
  ).toBeVisible();
  await expect(eventBubble(page, alpha)).toContainText(
    "Source adapter research",
  );
  await expect(eventBubble(page, beta)).toContainText("Parser tool build");
  await page
    .getByRole("button", {
      name: "Source adapter research: Writing. Inspect agent",
      exact: true,
    })
    .click();
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(inspector).toContainText("Tools R&D task");
  await expect(
    inspector.locator(".detail-row").filter({ hasText: "Parent" }),
  ).toContainText("Planner");
  await expect(inspector.locator(".agent-model-note")).toContainText(
    "rd-private-model",
  );
  await expect(inspector.locator(".agent-model-note")).toContainText(
    "Inherited from Tools R&D lead",
  );
  await expect(
    inspector.getByRole("button", { name: "Send guidance to agent" }),
  ).toBeDisabled();
  await expect(inspector).toContainText(
    "Only Planner or Engineering lead may call this agent.",
  );
  await page.getByRole("tab", { name: /^Files/ }).click();
  await expect(
    inspector.getByText("alpha-report.md", { exact: true }),
  ).toBeVisible();
  await expect(
    inspector.getByText("beta-tool.py", { exact: true }),
  ).toHaveCount(0);
  await expect(
    inspector.getByText("legacy-role-report.md", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", {
      name: "Parser tool build: Writing. Inspect agent",
      exact: true,
    })
    .click();
  await page.getByRole("tab", { name: /^Files/ }).click();
  await expect(
    inspector.getByText("beta-tool.py", { exact: true }),
  ).toBeVisible();
  await expect(
    inspector.getByText("alpha-report.md", { exact: true }),
  ).toHaveCount(0);
  await page.evaluate(() =>
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      event_id: "rd-alpha-progress",
      seq: 73,
      source: "harness",
      agent_id: "specialist:run-fixture:rd-alpha",
      run_id: "run-fixture",
      kr_id: "KR2",
      activity: "reading",
      summary: "Checking the adapter's saved proof",
      data: { tool_name: "read_artifact" },
      timestamp: "2026-10-21T10:00:01Z",
    }),
  );
  await expect(eventBubble(page, alpha)).toHaveAttribute(
    "title",
    /Source adapter research.*Checking the adapter's saved proof/,
  );
  await page
    .getByRole("button", {
      name: "Source adapter research: Reading. Inspect agent",
      exact: true,
    })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(
    inspector.getByText("Checking the adapter's saved proof", { exact: true }),
  ).toBeVisible();
  await expect(
    inspector.getByText("Saved private R&D evidence 1", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", {
      name: "External R&D mirror: Writing. Inspect agent",
      exact: true,
    })
    .click();
  await expect(
    inspector.locator(".detail-row").filter({ hasText: "Department" }),
  ).toContainText("Integrations");
  await expect(inspector.locator(".agent-model-note")).toHaveCount(0);
  await page.getByRole("tab", { name: /^Files/ }).click();
  await expect(
    inspector.getByText("alpha-report.md", { exact: true }),
  ).toHaveCount(0);
  await expect(
    inspector.getByText("beta-tool.py", { exact: true }),
  ).toHaveCount(0);
});
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
  worker_timeout: 3600,
  model_call_budget: {
    max_model_calls: 100,
    worker_model_calls: 12,
    max_tool_calls: 200,
  },
  web_search: { provider: "exa", configured: true },
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
  limits: {
    max_model_calls: 100,
    worker_model_calls: 12,
    max_tool_calls: 200,
    worker_timeout: 3600,
    command_timeout: 300,
  },
  model_calls: 10,
  tool_calls: 5,

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
  settingsOverrides: Partial<WorkspaceSettings> = {},
) {
  let run: Run = {
    ...initialRun,
    model_config: defaultSettings.defaults,
    ...overrides,
  };
  let settings = { ...structuredClone(defaultSettings), ...settingsOverrides };
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
    if (path === "/api/settings/budgets" && method === "PUT") {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
      settings = { ...settings, model_call_budget: body };
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
    if (path === "/api/events/history")
      return route.fulfill({
        json: {
          events: [],
          next_before: null,
          has_more: false,
          generation:
            new URL(route.request().url()).searchParams.get("generation") ??
            "fixture-generation",
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
    if (path === `/api/runs/${runId}/budgets` && method === "PUT") {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
      if (!["paused", "review", "failed"].includes(run.status))
        return route.fulfill({
          status: 409,
          json: { detail: "Pause the mission before changing its budgets." },
        });
      run = { ...run, limits: { ...run.limits, ...body } };
      return route.fulfill({ json: run });
    }
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
    page.getByRole("button", { name: "Open activity stream" }),
  ).toHaveCount(0);
  await expect(eventBubble(page, "backend_coder")).toContainText(
    "Running acceptance tests",
  );
  const lastEvent = await eventBubble(page, "backend_coder").boundingBox();
  const avatar = await page
    .locator('.canvas-agent[data-agent-key="backend_coder"]')
    .boundingBox();
  expect(lastEvent).not.toBeNull();
  expect(avatar).not.toBeNull();
  expect(lastEvent!.y + lastEvent!.height).toBeLessThanOrEqual(
    avatar!.y + avatar!.height / 2,
  );
  await expect(eventBubble(page, "executive")).toHaveCount(0);
  await expect(page.locator(".office-footer")).toBeInViewport();
  await page
    .getByRole("button", { name: "Backend coder: Executing. Inspect agent" })
    .click();
  await expect(
    page
      .getByRole("complementary", { name: "Selected agent" })
      .getByText("Running acceptance tests"),
  ).toBeVisible();
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
  await expect(summaryBubble(page, "Reading integration notes")).toContainText(
    "Reading integration notes",
  );
  await expect(eventBubble(page, "backend_coder")).toContainText(
    "Running acceptance tests",
  );
  await page
    .getByRole("button", { name: "Backend Coder: Reading. Inspect agent" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Backend Coder", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("complementary", { name: "Selected agent" })
      .getByText("Reading integration notes", { exact: true }),
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
test("restores paginated agent history with exact mission and identity scopes without changing event bubbles", async ({
  page,
}) => {
  await fixture(page);
  const otherRun = {
    ...initialRun,
    run_id: "older-mission",
    user_request: "An older mission",
    status: "succeeded",
  };
  const history: ActivityEvent[] = Array.from({ length: 205 }, (_, index) => ({
    event_id: `saved-${index + 1}`,
    seq: index + 1,
    source: "harness",
    agent_id: "backend_coder",
    run_id: runId,
    activity: "writing",
    summary: `Saved worker step ${index + 1}`,
    timestamp: "2026-10-18T09:00:00Z",
  }));
  history.push({
    ...history[0],
    seq: 206,
    event_id: "saved-sibling",
    agent_id: "system_architect",
    summary: "Sibling architecture activity",
  });
  history.push({
    ...history[0],
    seq: 207,
    event_id: "saved-other-mission",
    run_id: otherRun.run_id,
    summary: "Activity belonging to the older mission",
  });
  await page.route("**/api/runs", (route) =>
    route.fulfill({ json: [initialRun, otherRun] }),
  );
  await page.route(`**/api/runs/${otherRun.run_id}`, (route) =>
    route.fulfill({ json: otherRun }),
  );
  const historyRequests: string[] = [];
  await page.route("**/api/events/history?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    historyRequests.push(query.toString());
    const before = Number(query.get("before") || Infinity);
    const matching = history
      .filter(
        (event) =>
          event.seq < before &&
          (!query.get("run_id") || event.run_id === query.get("run_id")) &&
          (!query.get("agent_id") ||
            event.agent_id === query.get("agent_id")) &&
          (!query.get("source") || event.source === query.get("source")),
      )
      .sort((a, b) => b.seq - a.seq);
    const events = matching.slice(0, 100);
    return route.fulfill({
      json: {
        events,
        has_more: matching.length > events.length,
        next_before:
          matching.length > events.length ? events.at(-1)!.seq : null,
        generation: "fixture-generation",
      },
    });
  });
  await page.reload();
  await expect(page.getByText("Office connected")).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "Backend coder: Executing. Inspect agent",
    }),
  ).toBeVisible();
  await expect(eventBubble(page, "backend_coder")).toContainText(
    "Running acceptance tests",
  );
  await page
    .getByRole("button", { name: "Backend coder: Executing. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(inspector.locator(".agent-event")).toHaveCount(100);
  await expect(
    inspector.getByText("Sibling architecture activity"),
  ).toHaveCount(0);
  await inspector
    .getByRole("button", { name: "Load earlier activity" })
    .click();
  await expect(inspector.locator(".agent-event")).toHaveCount(200);
  await inspector
    .getByRole("button", { name: "Load earlier activity" })
    .click();
  await expect(inspector.locator(".agent-event")).toHaveCount(205);
  await expect(
    inspector.getByText("Saved worker step 1", { exact: true }),
  ).toBeVisible();
  await expect(
    inspector.getByRole("button", { name: "Load earlier activity" }),
  ).toHaveCount(0);
  await page
    .getByRole("combobox", { name: "Selected mission" })
    .selectOption(otherRun.run_id);
  await expect(
    inspector.getByText("Activity belonging to the older mission"),
  ).toBeVisible();
  await expect(
    inspector.getByText("Saved worker step 205", { exact: true }),
  ).toHaveCount(0);
  await expect(eventBubble(page, "backend_coder")).toContainText(
    "Running acceptance tests",
  );
  await expect(eventBubble(page, "backend_coder")).not.toContainText(
    "older mission",
  );
  expect(
    historyRequests.some(
      (query) =>
        query.includes("before=") &&
        query.includes("agent_id=backend_coder") &&
        query.includes("source=harness"),
    ),
  ).toBe(true);
  expect(
    await page.evaluate(
      () =>
        (
          window as unknown as { __officeStreams: EventSource[] }
        ).__officeStreams.at(-1)?.url,
    ),
  ).toContain("after=10");
});

test("hides error bubbles while retaining terminal events and exact agent history", async ({
  page,
}) => {
  await fixture(page);
  await expect(page.locator(".agent-event-bubble")).toHaveCount(1);
  await expect(eventBubble(page, "executive")).toHaveCount(0);
  const currentSpecialist = "specialist:run-fixture:0000000000000001";
  const olderSpecialist = "specialist:older-run:0000000000000001";
  await page.evaluate(
    ({ currentSpecialist, olderSpecialist }) => {
      const emit = (
        window as unknown as { __officeEmit: (event: unknown) => void }
      ).__officeEmit;
      for (const event of [
        {
          seq: 11,
          agent_id: "backend_coder",
          source: "harness",
          activity: "completed",
          summary: "Saved the completed implementation",
          run_id: "run-fixture",
        },
        {
          seq: 12,
          agent_id: "backend_coder",
          source: "harness",
          activity: "error",
          summary: "Verification needs the missing credentials",
          run_id: "run-fixture",
        },
        {
          seq: 13,
          agent_id: "backend_coder",
          source: "custom",
          activity: "reading",
          summary: "External monitor read its own integration feed",
          run_id: "run-fixture",
        },
        {
          seq: 14,
          agent_id: currentSpecialist,
          source: "harness",
          activity: "completed",
          summary: "Verified the current mission shader output",
          run_id: "run-fixture",
          data: {
            agent_type: "engineering_specialist",
            display_name: "Shader verifier",
            model_parent: "backend_coder",
          },
        },
        {
          seq: 15,
          agent_id: olderSpecialist,
          source: "harness",
          activity: "error",
          summary: "Older mission shader requires a different input",
          run_id: "older-run",
          data: {
            agent_type: "engineering_specialist",
            display_name: "Shader verifier",
            model_parent: "backend_coder",
          },
        },
      ])
        emit({
          ...event,
          event_id: `latest-${event.seq}`,
          timestamp: "2026-10-18T10:00:05Z",
        });
    },
    { currentSpecialist, olderSpecialist },
  );
  const worker = eventBubble(page, "backend_coder");
  await expect(worker).toHaveCount(0);
  await expect(
    summaryBubble(page, "External monitor read its own integration feed"),
  ).toHaveCount(1);
  await expect(eventBubble(page, currentSpecialist)).toContainText(
    "Verified the current mission shader output",
  );
  await expect(
    eventBubble(page, currentSpecialist).locator(".agent-event-name"),
  ).toHaveText("Shader verifier");
  await expect(eventBubble(page, currentSpecialist)).toHaveAccessibleName(
    /Last event: Completed/,
  );
  await expect(eventBubble(page, currentSpecialist)).toHaveAttribute(
    "data-run-id",
    runId,
  );
  await expect(eventBubble(page, olderSpecialist)).toHaveCount(0);
  await expect(page.locator(".agent-event-bubble")).toHaveCount(2);
  await page
    .getByRole("button", {
      name: "Backend coder: Needs attention. Inspect agent",
    })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(
    inspector.getByText("Saved the completed implementation", { exact: true }),
  ).toBeVisible();
  await expect(
    inspector.getByText("Verification needs the missing credentials", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    inspector.getByText("External monitor read its own integration feed"),
  ).toHaveCount(0);
  await page.evaluate(() => {
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      seq: 16,
      event_id: "worker-recovered",
      timestamp: "2026-10-18T10:00:06Z",
      agent_id: "backend_coder",
      source: "harness",
      run_id: "run-fixture",
      activity: "executing",
      summary: "Credentials available; resumed verification",
    });
  });
  await expect(worker).toContainText(
    "Credentials available; resumed verification",
  );
  await expect(worker).toHaveAccessibleName(/Last event: Executing/);
  await expect(worker.locator(".agent-event-name")).toHaveText("Backend coder");
  await expect(worker.locator(".agent-event-recency")).toHaveText("Last");
  await expect(worker).toHaveAttribute("data-event-seq", "16");
  await expect(worker).toHaveAttribute("data-run-id", runId);
  await page.evaluate(() => {
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      seq: 17,
      event_id: "external-warning",
      timestamp: "2026-10-18T10:00:07Z",
      agent_id: "backend_coder",
      source: "custom",
      activity: "error",
      summary: "External monitor needs attention",
    });
  });
  await expect(
    summaryBubble(page, "External monitor read its own integration feed"),
  ).toHaveCount(0);
  await expect(
    summaryBubble(page, "External monitor needs attention"),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", {
      name: "Backend Coder: Needs attention. Inspect agent",
      exact: true,
    }),
  ).toBeVisible();
});

test("hides stale working bubbles when the mission marks the avatar as an error", async ({
  page,
}) => {
  await fixture(page, {
    status: "failed",
    error: "Execution failed during verification",
  });
  await page.route("**/api/events/history?*", (route) =>
    route.fulfill({
      json: {
        events: [
          {
            agent_id: "backend_coder",
            source: "harness",
            run_id: runId,
            seq: 10,
            event_id: "saved-before-failure",
            activity: "executing",
            summary: "Running acceptance tests",
            timestamp: "2026-10-18T10:00:00Z",
          },
        ],
        next_before: null,
        has_more: false,
        generation: "fixture-generation",
      },
    }),
  );
  await page.reload();
  await expect(eventBubble(page, "backend_coder")).toHaveCount(0);
  await page
    .getByRole("button", {
      name: "Backend coder: Needs attention. Inspect agent",
      exact: true,
    })
    .click();
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(inspector.getByText("Error", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(
    inspector.getByText("Running acceptance tests", { exact: true }),
  ).toBeVisible();
});

test("keeps external tuple identities distinct from internal specialists and one another", async ({
  page,
}) => {
  await fixture(page);
  const specialist = "specialist:run-fixture:0000000000000001";
  await page.evaluate((specialist) => {
    const emit = (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit;
    const identities = [
      {
        agent_id: specialist,
        source: "harness",
        summary: "Internal specialist output",
        data: {
          display_name: "Internal verifier",
          agent_type: "engineering_specialist",
          model_parent: "backend_coder",
        },
      },
      {
        agent_id: "run-fixture:0000000000000001",
        source: "specialist",
        summary: "External specialist-shaped ID",
        data: {
          display_name: "External lookalike",
          agent_type: "engineering_specialist",
        },
      },
      {
        agent_id: "b:c",
        source: "a",
        summary: "First independent colon identity",
        data: { display_name: "Colon monitor A" },
      },
      {
        agent_id: "c",
        source: "a:b",
        summary: "Second independent colon identity",
        data: { display_name: "Colon monitor B" },
      },
    ];
    identities.forEach((identity, index) =>
      emit({
        ...identity,
        seq: 11 + index,
        event_id: `collision-${index}`,
        run_id: "run-fixture",
        activity: "reading",
        timestamp: "2026-10-18T10:00:05Z",
      }),
    );
  }, specialist);
  const summaries = [
    "Internal specialist output",
    "External specialist-shaped ID",
    "First independent colon identity",
    "Second independent colon identity",
  ];
  const keys = [];
  for (const summary of summaries) {
    const bubble = summaryBubble(page, summary);
    await expect(bubble).toHaveCount(1);
    const key = await bubble.getAttribute("data-agent-key");
    expect(key).toBeTruthy();
    keys.push(key);
  }
  expect(new Set(keys).size).toBe(4);
  await expect(eventBubble(page, specialist)).toContainText(
    "Internal specialist output",
  );
  for (const name of [
    "Internal verifier",
    "External lookalike",
    "Colon monitor A",
    "Colon monitor B",
  ]) {
    await page
      .getByRole("button", {
        name: `${name}: Reading. Inspect agent`,
        exact: true,
      })
      .click();
    const inspector = page.getByRole("complementary", {
      name: "Selected agent",
    });
    await expect(
      inspector.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
    await expect(
      inspector.locator(".detail-row").filter({ hasText: "Department" }),
    ).toContainText(
      name === "Internal verifier" ? "Engineering" : "Integrations",
    );
  }
});

test("keeps the newest snapshot event when older duplicate actor rows follow it", async ({
  page,
}) => {
  await fixture(page);
  const base = {
    agent_id: "backend_coder",
    run_id: runId,
    timestamp: "2026-10-18T10:00:05Z",
  };
  await page.route("**/api/office", (route) =>
    route.fulfill({
      json: {
        agents: [
          {
            ...base,
            source: "harness",
            seq: 12,
            event_id: "new-internal",
            activity: "error",
            summary: "Newest internal verification needs attention",
          },
          {
            ...base,
            source: "custom",
            seq: 14,
            event_id: "new-external",
            activity: "reading",
            summary: "Newest external monitor source",
          },
          {
            ...base,
            source: "harness",
            seq: 11,
            event_id: "old-internal",
            activity: "completed",
            summary: "Stale internal snapshot summary",
          },
          {
            ...base,
            source: "custom",
            seq: 13,
            event_id: "old-external",
            activity: "writing",
            summary: "Stale external snapshot summary",
          },
        ],
        cursor: 14,
        generation: "fixture-generation",
      },
    }),
  );
  await page.reload();
  await expect(eventBubble(page, "backend_coder")).toHaveCount(0);
  await page
    .getByRole("button", {
      name: "Backend coder: Needs attention. Inspect agent",
      exact: true,
    })
    .click();
  await expect(
    page
      .getByRole("complementary", { name: "Selected agent" })
      .getByText("Newest internal verification needs attention", {
        exact: true,
      }),
  ).toBeVisible();
  await expect(
    summaryBubble(page, "Newest external monitor source"),
  ).toHaveAttribute("data-event-seq", "14");
  await expect(
    summaryBubble(page, "Stale internal snapshot summary"),
  ).toHaveCount(0);
  await expect(
    summaryBubble(page, "Stale external snapshot summary"),
  ).toHaveCount(0);
  await expect(page.locator(".agent-event-bubble")).toHaveCount(1);
});

test("fits seven recorded agents beside a paused review banner without office or page scrolling", async ({
  page,
}) => {
  await page.setViewportSize({ width: 867, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await fixture(page, {
    status: "review",
    review: {
      interrupt_id: "paused-source-review",
      kind: "blocked",
      reason:
        "A required reference was unavailable. Choose how the team should continue.",
      allowed_actions: ["provide_context", "revise_kr", "abort"],
    },
  });
  const specialistData = {
    agent_type: "engineering_specialist",
    parent_agent_id: "engineering_head",
    model_parent: "backend_coder",
  };
  const actors: ActivityEvent[] = [
    {
      agent_id: "executive",
      activity: "waiting",
      summary: "Waiting for the engineering review decision",
    },
    {
      agent_id: "engineering_head",
      activity: "error",
      summary: "The required reference needs a corrected public URL",
    },
    {
      agent_id: "engineering_gatekeeper",
      activity: "error",
      summary: "The source evidence is incomplete for the requested output",
    },
    {
      agent_id: "tools_rd_lead",
      activity: "completed",
      summary: "Returned an evidence-backed report to the Engineering lead",
    },
    {
      agent_id: "triage_router",
      activity: "completed",
      summary: "Selected Engineering departmental execution",
    },
    {
      agent_id: "specialist:run-fixture:0000000000000001",
      activity: "completed",
      summary: "Saved the implementation and its verification output",
      data: { ...specialistData, display_name: "Implementation specialist" },
    },
    {
      agent_id: "specialist:run-fixture:0000000000000002",
      activity: "error",
      summary: "The outdated source URL returned no readable page",
      data: { ...specialistData, display_name: "Source analyst" },
    },
  ].map((actor, index) => ({
    ...actor,
    activity: actor.activity as ActivityEvent["activity"],
    source: "harness",
    run_id: runId,
    seq: 11 + index,
    event_id: `paused-${index}`,
    timestamp: "2026-10-18T10:00:05Z",
  }));
  await page.route("**/api/office", (route) =>
    route.fulfill({
      json: { agents: actors, cursor: 17, generation: "fixture-generation" },
    }),
  );
  const triage = actors.find((actor) => actor.agent_id === "triage_router")!;
  await page.route("**/api/events/history?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    const matches =
      query.get("agent_id") === "triage_router" &&
      query.get("source") === "harness" &&
      query.get("run_id") === runId;
    const events = matches
      ? [
          triage,
          ...[
            "Received the mission",
            "Evaluated the requested task scope",
            "Checked the available departments",
          ].map((summary, index) => ({
            ...triage,
            seq: index + 1,
            event_id: `triage-history-${index}`,
            summary,
          })),
        ]
      : [];
    return route.fulfill({
      json: {
        events,
        next_before: null,
        has_more: false,
        generation: "fixture-generation",
      },
    });
  });
  await page.reload();
  await expect(page.locator(".review-banner")).toBeVisible();
  await expect(page.locator(".agent-event-bubble")).toHaveCount(4);
  for (const actor of actors)
    if (actor.activity === "error")
      await expect(eventBubble(page, actor.agent_id)).toHaveCount(0);
    else
      await expect(eventBubble(page, actor.agent_id)).toContainText(
        actor.summary!,
      );
  await expect(eventBubble(page, "backend_coder")).toHaveCount(0);
  await expect
    .poll(() =>
      page
        .locator(".office-scroll-region")
        .evaluate(
          (node) =>
            node.scrollWidth <= node.clientWidth &&
            node.scrollHeight <= node.clientHeight,
        ),
    )
    .toBe(true);
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <= window.innerWidth &&
        document.documentElement.scrollHeight <= window.innerHeight,
    ),
  ).toBe(true);
  await eventBubble(page, "triage_router").click();
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(
    inspector.getByRole("heading", { name: "Triage Router", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(inspector.locator(".agent-event")).toHaveCount(4);
  await expect(
    inspector.getByText(triage.summary!, { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/office-bubbles-paused-867.png",
    fullPage: true,
  });
});

for (const { width, height } of [
  { width: 1440, height: 1000 },
  { width: 867, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`keeps dense event bubbles readable within the ${width}px office map and agent selection usable`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await fixture(page);
    const fullSummary =
      "Working from the recorded source and checking the required output. The final sentence must remain available to keyboard and assistive technology users.";
    await page.evaluate((fullSummary) => {
      const emit = (
        window as unknown as { __officeEmit: (event: unknown) => void }
      ).__officeEmit;
      const fixed = [
        "planner",
        "triage_router",
        "executive",
        "research_head",
        "market_researcher",
        "data_analyst",
        "engineering_head",
        "tools_rd_lead",
        "system_architect",
        "backend_coder",
        "research_gatekeeper",
        "engineering_gatekeeper",
      ];
      const actors = [
        ...fixed.map((agent_id) => ({ agent_id, source: "harness", data: {} })),
        ...Array.from({ length: 4 }, (_, index) => ({
          agent_id: `specialist:run-fixture:${String(index).padStart(16, "0")}`,
          source: "harness",
          data: {
            display_name: `Dense specialist ${index}`,
            agent_type: "engineering_specialist",
            model_parent: "backend_coder",
          },
        })),
        ...Array.from({ length: 3 }, (_, index) => ({
          agent_id: `monitor-${index}`,
          source: "custom-office",
          data: { display_name: `Dense integration ${index}` },
        })),
      ];
      actors.forEach((actor, index) =>
        emit({
          ...actor,
          seq: 11 + index,
          event_id: `dense-${index}`,
          run_id: "run-fixture",
          activity: "reading",
          summary: `${index + 1}. ${fullSummary}`,
          timestamp: "2026-10-18T10:00:05Z",
        }),
      );
    }, fullSummary);
    await expect(page.locator(".agent-event-bubble")).toHaveCount(19);
    const bounds = await page.locator(".office-canvas canvas").boundingBox();
    expect(bounds).not.toBeNull();
    const boxes = [];
    for (const bubble of await page.locator(".agent-event-bubble").all()) {
      const box = await bubble.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(bounds!.x - 1);
      expect(box!.y).toBeGreaterThanOrEqual(bounds!.y - 1);
      expect(box!.x + box!.width).toBeLessThanOrEqual(
        bounds!.x + bounds!.width + 1,
      );
      expect(box!.y + box!.height).toBeLessThanOrEqual(
        bounds!.y + bounds!.height + 1,
      );
      expect(await bubble.getAttribute("title")).toContain(fullSummary);
      expect(await bubble.getAttribute("aria-label")).toContain(fullSummary);
      boxes.push(box!);
    }
    for (let left = 0; left < boxes.length; left++)
      for (let right = left + 1; right < boxes.length; right++) {
        const a = boxes[left],
          b = boxes[right];
        expect(
          a.x + a.width <= b.x + 1 ||
            b.x + b.width <= a.x + 1 ||
            a.y + a.height <= b.y + 1 ||
            b.y + b.height <= a.y + 1,
        ).toBe(true);
      }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/office-bubbles-${width}.png`,
      fullPage: true,
    });
    await page
      .getByRole("button", {
        name: "Engineering reviewer: Reading. Inspect agent",
        exact: true,
      })
      .click();
    await expect(
      page
        .getByRole("complementary", { name: "Selected agent" })
        .getByRole("heading", { name: "Engineering reviewer", exact: true }),
    ).toBeVisible();
  });
}

test("activity history errors stay visible and retry restores source-isolated integration history", async ({
  page,
}) => {
  await fixture(page);
  let unavailable = true;
  await page.route("**/api/events/history?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    if (unavailable)
      return route.fulfill({
        status: 503,
        json: { detail: "Activity database temporarily unavailable" },
      });
    const events: ActivityEvent[] = [
      {
        seq: 8,
        event_id: "internal-history",
        source: "harness",
        agent_id: "backend_coder",
        run_id: runId,
        activity: "writing",
        summary: "Internal saved output",
        timestamp: "2026-10-18T09:00:00Z",
      },
      {
        seq: 9,
        event_id: "external-history",
        source: "custom",
        agent_id: "backend_coder",
        activity: "reading",
        summary: "External saved integration output",
        timestamp: "2026-10-18T09:00:01Z",
      },
    ].filter(
      (event) =>
        (!query.get("run_id") || event.run_id === query.get("run_id")) &&
        (!query.get("source") || event.source === query.get("source")) &&
        (!query.get("agent_id") || event.agent_id === query.get("agent_id")),
    ) as ActivityEvent[];
    return route.fulfill({
      json: {
        events,
        next_before: null,
        has_more: false,
        generation: "fixture-generation",
      },
    });
  });
  await page.reload();
  await page
    .getByRole("button", { name: "Backend coder: Executing. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(inspector.getByRole("alert")).toContainText(
    "Activity database temporarily unavailable",
  );
  await expect(inspector.getByText("The office is ready")).toHaveCount(0);
  unavailable = false;
  await inspector.getByRole("button", { name: "Retry activity" }).click();
  await expect(inspector.getByText("Internal saved output")).toBeVisible();
  await expect(inspector.getByRole("alert")).toHaveCount(0);
  await page.evaluate(() => {
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      seq: 11,
      event_id: "external-current",
      source: "custom",
      agent_id: "backend_coder",
      activity: "reading",
      summary: "External current integration state",
      timestamp: "2026-10-18T10:00:01Z",
    });
  });
  await page
    .getByRole("button", { name: "Backend Coder: Reading. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(
    inspector.getByText("External saved integration output"),
  ).toBeVisible();
  await expect(inspector.getByText("Internal saved output")).toHaveCount(0);
  await expect(
    summaryBubble(page, "External current integration state"),
  ).toHaveCount(1);
  await expect(
    summaryBubble(page, "External saved integration output"),
  ).toHaveCount(0);
});
test("retains every matching live event when a batched burst exceeds the animation buffer", async ({
  page,
}) => {
  await fixture(page);
  await page
    .getByRole("button", { name: "Backend coder: Executing. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(
    page.getByText("No activity recorded for this agent yet."),
  ).toBeVisible();
  await page.evaluate(() => {
    const emit = (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit;
    for (let seq = 11; seq <= 260; seq++)
      emit({
        seq,
        event_id: `burst-${seq}`,
        source: "harness",
        agent_id: "backend_coder",
        run_id: "run-fixture",
        activity: "writing",
        summary: `Batched worker event ${seq}`,
        timestamp: "2026-10-18T10:00:01Z",
      });
  });
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(inspector.locator(".agent-event")).toHaveCount(250);
  await expect(
    inspector.getByText("Batched worker event 11", { exact: true }),
  ).toBeVisible();
  await expect(eventBubble(page, "backend_coder")).toContainText(
    "Batched worker event 260",
  );
  await expect(eventBubble(page, "backend_coder")).not.toContainText(
    "Batched worker event 11",
  );
});
test("a history generation mismatch resets stale client data before loading the new history", async ({
  page,
}) => {
  await fixture(page);
  let snapshots = 0;
  await page.route("**/api/office", (route) => {
    snapshots++;
    return route.fulfill({
      json: {
        agents: [],
        cursor: snapshots === 1 ? 10 : 0,
        generation: snapshots === 1 ? "fixture-generation" : "history-reset",
      },
    });
  });
  await page.route("**/api/runs", (route) =>
    route.fulfill({ json: snapshots < 2 ? [initialRun] : [] }),
  );
  await page.route("**/api/events/history?*", (route) => {
    const old =
      new URL(route.request().url()).searchParams.get("generation") !==
      "history-reset";
    return route.fulfill({
      json: {
        events: [],
        next_before: null,
        has_more: false,
        generation: "history-reset",
        cursor: 0,
        reset: old,
      },
    });
  });
  await page.reload();
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue("");
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as unknown as { __officeStreams: EventSource[] }
          ).__officeStreams.at(-1)?.url,
      ),
    )
    .toBe("/api/events?after=0&generation=history-reset");
  await expect(page.locator(".agent-event-bubble")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Backend coder: Idle. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(
    page.getByText("No activity recorded for this agent yet."),
  ).toBeVisible();
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
  await expect(
    page.getByRole("button", { name: "Open activity stream" }),
  ).toHaveCount(0);
  await expect(eventBubble(page, "backend_coder")).toContainText(
    "Running acceptance tests",
  );
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
test("workspace settings report the server search provider without exposing a new save control", async ({
  page,
}) => {
  const requests = await fixture(page);
  let search: WorkspaceSettings["web_search"] = defaultSettings.web_search;
  await page.route("**/api/settings", (route) =>
    route.fulfill({ json: { ...defaultSettings, web_search: search } }),
  );
  for (const [value, expected] of [
    [{ provider: "exa", configured: true }, "Web search: Exa"],
    [{ provider: "zai_mcp", configured: true }, "Web search: Z.AI MCP"],
    [
      { provider: "exa", configured: false },
      "Web search: Exa · Not configured",
    ],
    [
      { provider: "zai_mcp", configured: false },
      "Web search: Z.AI MCP · Not configured",
    ],
    [undefined, "Web search: Not reported"],
  ] as const) {
    search = value;
    await page.reload();
    await page.getByRole("button", { name: "Workspace settings" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(expected, { exact: true })).toBeVisible();
    await expect(
      dialog.getByRole("combobox", { name: /Web search/ }),
    ).toHaveCount(0);
    await expect(
      dialog.getByRole("textbox", { name: /API key|credential/i }),
    ).toHaveCount(0);
    await expect(
      dialog.getByRole("button", { name: "Save model settings", exact: true }),
    ).toBeEnabled();
  }
  expect(
    requests.some((request) => request.path.startsWith("/api/settings/")),
  ).toBe(false);
});
test("workspace call budgets persist independently of model drafts and agent overrides", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  const mission = dialog.getByRole("spinbutton", {
    name: "Model calls per mission",
    exact: true,
  });
  const worker = dialog.getByRole("spinbutton", {
    name: "Agent model turns per invocation",
    exact: true,
  });
  const model = dialog.getByRole("textbox", { name: "Model", exact: true });
  await expect(mission).toHaveValue("100");
  await expect(worker).toHaveValue("12");
  await expect(
    dialog.getByText("Worker timeout: 3600s", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByRole("combobox", { name: "Apply to", exact: true })
    .selectOption("system_architect");
  await model.fill("saved-architect-model");
  await dialog
    .getByRole("button", { name: "Save agent model", exact: true })
    .click();
  await expect(
    dialog.getByRole("button", { name: "Use default model", exact: true }),
  ).toBeVisible();
  await model.fill("unsaved-model-draft");
  await mission.fill("240");
  await worker.fill("24");
  await dialog
    .getByRole("button", { name: "Save call budget", exact: true })
    .click();
  await expect(
    dialog.getByText("Saved. New missions will use this call budget.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(model).toHaveValue("unsaved-model-draft");
  expect(
    requests.filter((request) =>
      request.path.startsWith("/api/settings/agents/"),
    ),
  ).toHaveLength(1);
  expect(
    requests.find((request) => request.path === "/api/settings/budgets")?.body,
  ).toEqual({
    max_model_calls: 240,
    worker_model_calls: 24,
    max_tool_calls: 200,
  });
  await mission.fill("300");
  const workerUnlimited = dialog.getByRole("checkbox", {
    name: "No limit for agent model turns per invocation",
    exact: true,
  });
  await workerUnlimited.check();
  await model.fill("updated-architect-model");
  await dialog
    .getByRole("button", { name: "Save agent model", exact: true })
    .click();
  await expect(
    dialog.getByText(
      "Saved. New missions will use this model for System architect.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(mission).toHaveValue("300");
  await expect(workerUnlimited).toBeChecked();
  await expect(worker).toBeDisabled();
  await workerUnlimited.uncheck();
  await expect(worker).toHaveValue("24");
  await dialog
    .getByRole("combobox", { name: "Apply to", exact: true })
    .selectOption("all");
  await expect(mission).toHaveValue("300");
  await dialog.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Workspace settings" }).click();
  await expect(mission).toHaveValue("240");
  await expect(worker).toHaveValue("24");
  await page.reload();
  await page.getByRole("button", { name: "Workspace settings" }).click();
  await expect(mission).toHaveValue("240");
  await expect(worker).toHaveValue("24");
  await dialog
    .getByRole("combobox", { name: "Apply to", exact: true })
    .selectOption("system_architect");
  await expect(model).toHaveValue("updated-architect-model");
  await expect(
    dialog.getByRole("button", { name: "Use default model", exact: true }),
  ).toBeVisible();
  expect(
    requests.some((request) => request.path === "/api/settings/model"),
  ).toBe(false);
});

test("No limit budgets persist as independent nulls, retry failed saves, and restore finite drafts", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  const mission = dialog.getByRole("spinbutton", {
    name: "Model calls per mission",
    exact: true,
  });
  const worker = dialog.getByRole("spinbutton", {
    name: "Agent model turns per invocation",
    exact: true,
  });
  const missionUnlimited = dialog.getByRole("checkbox", {
    name: "No limit for model calls per mission",
    exact: true,
  });
  const workerUnlimited = dialog.getByRole("checkbox", {
    name: "No limit for agent model turns per invocation",
    exact: true,
  });
  const save = dialog.getByRole("button", {
    name: "Save call budget",
    exact: true,
  });
  await mission.fill("240");
  await worker.fill("24");
  await missionUnlimited.check();
  await expect(mission).toBeDisabled();
  await expect(mission).toHaveValue("");
  await expect(worker).toBeEnabled();
  await missionUnlimited.uncheck();
  await expect(mission).toHaveValue("240");
  await mission.fill("");
  await worker.fill("");
  await expect(save).toBeDisabled();
  await missionUnlimited.check();
  await workerUnlimited.check();
  await expect(save).toBeEnabled();
  await expect(
    dialog.getByText(/A finite call cap keeps governed review behavior/i),
  ).toBeVisible();
  let rejectSave = true;
  await page.route("**/api/settings/budgets", (route) =>
    rejectSave
      ? route.fulfill({
          status: 503,
          json: { detail: "Budget storage unavailable" },
        })
      : route.fallback(),
  );
  await save.click();
  const budget = dialog.getByRole("region", {
    name: "Call budgets",
    exact: true,
  });
  await expect(budget.getByRole("alert")).toContainText(
    "Budget storage unavailable",
  );
  await expect(missionUnlimited).toBeChecked();
  await expect(workerUnlimited).toBeChecked();
  rejectSave = false;
  await save.click();
  await expect(budget.getByRole("alert")).toHaveCount(0);
  await expect(budget.getByRole("status")).toContainText("Saved.");
  expect(
    requests
      .filter((request) => request.path === "/api/settings/budgets")
      .at(-1)?.body,
  ).toEqual({
    max_model_calls: null,
    worker_model_calls: null,
    max_tool_calls: 200,
  });
  await missionUnlimited.uncheck();
  await expect(mission).toHaveValue("240");
  await missionUnlimited.check();
  await workerUnlimited.uncheck();
  await expect(worker).toHaveValue("24");
  await workerUnlimited.check();
  await page.reload();
  await page.getByRole("button", { name: "Workspace settings" }).click();
  await expect(missionUnlimited).toBeChecked();
  await expect(workerUnlimited).toBeChecked();
  await expect(mission).toBeDisabled();
  await expect(worker).toBeDisabled();
  await missionUnlimited.uncheck();
  await expect(mission).toHaveValue("100");
  await save.click();
  await expect(budget.getByRole("status")).toContainText("Saved.");
  expect(
    requests
      .filter((request) => request.path === "/api/settings/budgets")
      .at(-1)?.body,
  ).toEqual({
    max_model_calls: 100,
    worker_model_calls: null,
    max_tool_calls: 200,
  });
  await page.reload();
  await page.getByRole("button", { name: "Workspace settings" }).click();
  await expect(missionUnlimited).not.toBeChecked();
  await expect(workerUnlimited).toBeChecked();
  await missionUnlimited.check();
  await workerUnlimited.uncheck();
  await expect(worker).toHaveValue("12");
  await save.click();
  await expect(budget.getByRole("status")).toContainText("Saved.");
  expect(
    requests
      .filter((request) => request.path === "/api/settings/budgets")
      .at(-1)?.body,
  ).toEqual({
    max_model_calls: null,
    worker_model_calls: 12,
    max_tool_calls: 200,
  });
  await page.reload();
  await page.getByRole("button", { name: "Workspace settings" }).click();
  await expect(missionUnlimited).toBeChecked();
  await expect(workerUnlimited).not.toBeChecked();
  await expect(worker).toBeEnabled();
  expect(
    requests.some((request) => request.path === "/api/settings/model"),
  ).toBe(false);
});
test("tool No limit can be saved and explicitly applied to the exhausted mission without resuming it", async ({
  page,
}) => {
  const recordedReview = {
    interrupt_id: "budget-review",
    kind: "blocked",
    reason: "Run tool call budget exhausted",
  };
  const requests = await fixture(
    page,
    {
      status: "review",
      review: recordedReview,
      model_calls: 110,
      tool_calls: 200,
      limits: {
        max_model_calls: null,
        worker_model_calls: null,
        max_tool_calls: 200,
        worker_timeout: 3600,
        command_timeout: 300,
      },
    },
    undefined,
    {
      // Existing two-field saved preferences did not remove the tool cap.
      model_call_budget: {
        max_model_calls: null,
        worker_model_calls: null,
      },
    },
  );
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  const budget = dialog.getByRole("region", {
    name: "Call budgets",
    exact: true,
  });
  const selected = budget.getByRole("region", {
    name: "Selected mission call budgets",
    exact: true,
  });
  const tools = budget.getByRole("spinbutton", {
    name: "Tool calls per mission",
    exact: true,
  });
  const toolUnlimited = budget.getByRole("checkbox", {
    name: "No limit for tool calls per mission",
    exact: true,
  });
  const apply = selected.getByRole("button", {
    name: "Apply saved budgets to this mission",
    exact: true,
  });
  await expect(tools).toHaveValue("200");
  await expect(toolUnlimited).not.toBeChecked();
  await expect(selected.getByText("200 used · limit: 200")).toBeVisible();
  await expect(selected.getByText("110 used · limit: No limit")).toBeVisible();
  await dialog
    .getByRole("textbox", { name: "Model", exact: true })
    .fill("unsaved-model-draft");
  await toolUnlimited.check();
  await expect(tools).toBeDisabled();
  await expect(tools).toHaveValue("");
  await expect(apply).toBeDisabled();
  await expect(
    selected.getByText("Save changes before applying them to this mission."),
  ).toBeVisible();
  await budget
    .getByRole("button", { name: "Save call budget", exact: true })
    .click();
  await expect(apply).toBeEnabled();
  expect(
    requests.find((request) => request.path === "/api/settings/budgets")?.body,
  ).toEqual({
    max_model_calls: null,
    worker_model_calls: null,
    max_tool_calls: null,
  });
  // Saving defaults never silently changes a mission's recorded limits.
  await expect(selected.getByText("200 used · limit: 200")).toBeVisible();
  let rejectApply = true;
  await page.route(`**/api/runs/${runId}/budgets`, (route) =>
    rejectApply
      ? route.fulfill({
          status: 409,
          json: { detail: "The worker is still finishing its current step." },
        })
      : route.fallback(),
  );
  await apply.click();
  await expect(selected.getByRole("alert")).toContainText(
    "worker is still finishing",
  );
  await expect(selected.getByText("200 used · limit: 200")).toBeVisible();
  rejectApply = false;
  await apply.click();
  await expect(selected.getByRole("alert")).toHaveCount(0);
  await expect(selected.getByRole("status")).toContainText(
    "Autonomous mode may continue this mission automatically",
  );
  await expect(selected.getByText("200 used · limit: No limit")).toBeVisible();
  await expect(
    dialog.getByRole("textbox", { name: "Model", exact: true }),
  ).toHaveValue("unsaved-model-draft");
  const current = await page.evaluate(
    async (id) => (await fetch(`/api/runs/${id}`)).json(),
    runId,
  );
  expect(current).toMatchObject({
    status: "review",
    review: recordedReview,
    model_calls: 110,
    tool_calls: 200,
    limits: {
      max_model_calls: null,
      worker_model_calls: null,
      max_tool_calls: null,
      worker_timeout: 3600,
      command_timeout: 300,
    },
  });
  expect(
    requests.find((request) => request.path === `/api/runs/${runId}/budgets`)
      ?.body,
  ).toEqual({
    max_model_calls: null,
    worker_model_calls: null,
    max_tool_calls: null,
  });
  expect(
    requests.some((request) => /\/(resume|retry)$/.test(request.path)),
  ).toBe(false);
  await toolUnlimited.uncheck();
  await expect(tools).toHaveValue("200");
  await expect(apply).toBeDisabled();
  // Unsaved edits cannot reapply the old finite value by accident.
  await expect(selected.getByText("200 used · limit: No limit")).toBeVisible();
  await page.screenshot({
    path: "test-results/tool-budget-recovery.png",
    fullPage: true,
  });
});

test("running missions expose actual usage without allowing a live budget replacement", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const selected = page.getByRole("region", {
    name: "Selected mission call budgets",
    exact: true,
  });
  await expect(selected.getByText("5 used · limit: 200")).toBeVisible();
  await expect(
    selected.getByRole("button", {
      name: "Apply saved budgets to this mission",
    }),
  ).toHaveCount(0);
  expect(requests.some((request) => request.path.endsWith("/budgets"))).toBe(
    false,
  );
});

test("call budget validation prevents invalid writes and failed saves can be retried on mobile", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const requests = await fixture(page);
  await page.getByRole("button", { name: "Workspace settings" }).click();
  const dialog = page.getByRole("dialog");
  const mission = dialog.getByRole("spinbutton", {
    name: "Model calls per mission",
    exact: true,
  });
  const worker = dialog.getByRole("spinbutton", {
    name: "Agent model turns per invocation",
    exact: true,
  });
  const save = dialog.getByRole("button", {
    name: "Save call budget",
    exact: true,
  });
  for (const invalid of ["", "0", "-1", "1.5", "10001"]) {
    await mission.fill(invalid);
    await expect(mission).toHaveAttribute("aria-invalid", "true");
    await expect(save).toBeDisabled();
    await mission.press("Enter");
  }
  await mission.fill("240");
  for (const invalid of ["", "0", "-1", "12.5", "101"]) {
    await worker.fill(invalid);
    await expect(worker).toHaveAttribute("aria-invalid", "true");
    await expect(save).toBeDisabled();
    await worker.press("Enter");
  }
  expect(
    requests.some((request) => request.path === "/api/settings/budgets"),
  ).toBe(false);
  await worker.fill("24");
  const tools = dialog.getByRole("spinbutton", {
    name: "Tool calls per mission",
    exact: true,
  });
  for (const invalid of ["", "0", "-1", "1.5", "100001"]) {
    await tools.fill(invalid);
    await expect(tools).toHaveAttribute("aria-invalid", "true");
    await expect(save).toBeDisabled();
    await tools.press("Enter");
  }
  await tools.fill("450");
  let rejectSave = true;
  let attempts = 0;
  await page.route("**/api/settings/budgets", (route) => {
    attempts++;
    return rejectSave
      ? route.fulfill({
          status: 503,
          json: { detail: "Call budget storage is temporarily unavailable" },
        })
      : route.fallback();
  });
  await save.click();
  const budget = dialog.getByRole("region", {
    name: "Call budgets",
    exact: true,
  });
  await expect(budget.getByRole("alert")).toContainText(
    "Call budget storage is temporarily unavailable",
  );
  await expect(budget.getByRole("status")).toHaveCount(0);
  await expect(mission).toHaveValue("240");
  await expect(worker).toHaveValue("24");
  rejectSave = false;
  await save.click();
  await expect(budget.getByRole("alert")).toHaveCount(0);
  await expect(
    budget.getByText("Saved. New missions will use this call budget.", {
      exact: true,
    }),
  ).toBeVisible();
  expect(attempts).toBe(2);
  expect(
    requests.filter((request) => request.path === "/api/settings/budgets"),
  ).toHaveLength(1);
  expect((await save.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
  expect(
    await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth),
  ).toBe(true);
  await budget.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "test-results/call-budget-mobile.png",
    fullPage: true,
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
  await dialog
    .getByRole("spinbutton", { name: "Model calls per mission", exact: true })
    .fill("220");
  await dialog
    .getByRole("spinbutton", {
      name: "Agent model turns per invocation",
      exact: true,
    })
    .fill("22");
  await dialog
    .getByRole("checkbox", {
      name: "No limit for model calls per mission",
      exact: true,
    })
    .check();
  await dialog
    .getByRole("checkbox", {
      name: "No limit for agent model turns per invocation",
      exact: true,
    })
    .check();
  await dialog
    .getByRole("button", { name: "Save call budget", exact: true })
    .click();
  await expect(
    dialog.getByText("Saved. New missions will use this call budget.", {
      exact: true,
    }),
  ).toBeVisible();
  await dialog
    .getByRole("checkbox", {
      name: "No limit for agent model turns per invocation",
      exact: true,
    })
    .uncheck();
  await dialog
    .getByRole("spinbutton", {
      name: "Agent model turns per invocation",
      exact: true,
    })
    .fill("33");
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
  await expect(
    dialog.getByRole("spinbutton", {
      name: "Model calls per mission",
      exact: true,
    }),
  ).toHaveValue("100");
  await expect(
    dialog.getByRole("spinbutton", {
      name: "Agent model turns per invocation",
      exact: true,
    }),
  ).toHaveValue("12");
  await expect(
    dialog.getByRole("checkbox", {
      name: "No limit for model calls per mission",
      exact: true,
    }),
  ).not.toBeChecked();
  await expect(
    dialog.getByRole("checkbox", {
      name: "No limit for agent model turns per invocation",
      exact: true,
    }),
  ).not.toBeChecked();
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
  await expect(page.locator(".agent-event-bubble")).toHaveCount(0);
});
test("another client reset event clears stale run data and reopens the stream at zero", async ({
  page,
}) => {
  const requests = await fixture(page);
  await page.route("**/api/office", (route) =>
    route.fulfill({ json: { agents: [], cursor: 0 } }),
  );
  await page.route("**/api/runs", (route) => route.fulfill({ json: [] }));
  await expect(eventBubble(page, "backend_coder")).toBeVisible();
  await page
    .getByRole("button", { name: "Backend coder: Executing. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await page.evaluate(() => {
    (window as unknown as { __officeReset: () => void }).__officeReset();
  });
  await expect(page.locator(".agent-event-bubble")).toHaveCount(0);
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
  await page
    .getByRole("button", { name: "Backend coder: Idle. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(
    page.getByText("No activity recorded for this agent yet."),
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
  await expect(eventBubble(page, "backend_coder")).toContainText(
    "Writing the final acceptance report",
  );
  await expect(eventBubble(page, "backend_coder")).not.toContainText(
    "Read acceptance results while disconnected",
  );
  await page
    .getByRole("button", { name: "Backend coder: Writing. Inspect agent" })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  const activity = page.getByRole("complementary", { name: "Selected agent" });
  await expect(
    activity.getByText("Read acceptance results while disconnected"),
  ).toBeVisible();
  await expect(
    activity.getByText("Writing the final acceptance report"),
  ).toBeVisible();
  await expect(activity.locator(".agent-event")).toHaveCount(2);
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
  await expect(summaryBubble(page, "Old generation activity")).toBeVisible();
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
  await expect(page.locator(".agent-event-bubble")).toHaveCount(0);
  await expect(
    page.getByRole("combobox", { name: "Selected mission" }),
  ).toHaveValue("");
  await expect(page.getByText("Old generation activity")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Old Agent/ })).toHaveCount(0);
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
    summaryBubble(page, "First activity after offline reset"),
  ).toBeVisible();
  await expect(page.locator(".agent-event-bubble")).toHaveCount(1);
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

for (const width of [867, 390]) {
  test(`follows a newly spawned specialist across pages at ${width}px without stealing selection or overriding manual paging`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await fixture(page);
    const actors = Array.from({ length: 6 }, (_, index) => ({
      agent_id: `specialist:run-fixture:${String(index + 1).padStart(16, "0")}`,
      source: "harness",
      run_id: runId,
      activity: "writing",
      summary: `Preparing specialist ${index + 1} output`,
      seq: 11 + index,
      event_id: `spawn-${index + 1}`,
      timestamp: "2026-10-18T10:00:05Z",
      data: {
        agent_type: "engineering_specialist",
        display_name:
          index === 4
            ? "bioRxiv Content Cartographer"
            : `Spawn specialist ${index + 1}`,
        parent_agent_id: "engineering_head",
        model_parent: "backend_coder",
      },
    }));
    const emit = async (events: object[]) =>
      page.evaluate((events) => {
        for (const event of events)
          (
            window as unknown as { __officeEmit: (event: unknown) => void }
          ).__officeEmit(event);
      }, events);
    await emit(actors.slice(0, 4));
    await page
      .getByRole("button", {
        name: "Spawn specialist 1: Writing. Inspect agent",
        exact: true,
      })
      .click();
    await emit([actors[4]]);
    await expect(
      page.getByText("Task specialists 5–5 of 5", { exact: true }),
    ).toBeVisible();
    await expect(eventBubble(page, actors[4].agent_id)).toContainText(
      "Preparing specialist 5 output",
    );
    const inspector = page.getByRole("complementary", {
      name: "Selected agent",
    });
    await expect(
      inspector.getByRole("heading", {
        name: "Spawn specialist 1",
        exact: true,
      }),
    ).toBeVisible();

    await page
      .getByRole("button", {
        name: "Previous Task specialists page",
        exact: true,
      })
      .click();
    await emit([
      {
        ...actors[4],
        seq: 20,
        event_id: "cartographer-progress",
        summary: "Reading the next paper section",
      },
    ]);
    await expect(
      page.getByText("Task specialists 1–4 of 5", { exact: true }),
    ).toBeVisible();
    await expect(eventBubble(page, actors[4].agent_id)).toHaveCount(0);

    await emit([
      {
        ...actors[5],
        seq: 21,
        activity: "completed",
        summary: "Completed before the next projection refresh",
      },
    ]);
    await expect(
      page.getByText("Task specialists 5–6 of 6", { exact: true }),
    ).toBeVisible();
    await expect(eventBubble(page, actors[5].agent_id)).toContainText(
      "Completed before the next projection refresh",
    );
    await expect(eventBubble(page, actors[4].agent_id)).toContainText(
      "Reading the next paper section",
    );
    await page.getByRole("button", { name: "Agents", exact: true }).click();
    await page
      .getByRole("textbox", { name: "Search agents" })
      .fill("Spawn specialist 1");
    await page
      .locator(".agent-list .agent-row")
      .filter({ hasText: "Spawn specialist 1" })
      .click();
    await page.getByRole("button", { name: "Office", exact: true }).click();
    await expect(
      page.getByText("Task specialists 1–4 of 6", { exact: true }),
    ).toBeVisible();
    await expect(eventBubble(page, actors[0].agent_id)).toBeVisible();
  });
}

test("new integrations follow their own page while ordinary updates preserve manual browsing", async ({
  page,
}) => {
  await fixture(page);
  const actors = Array.from({ length: 4 }, (_, index) => ({
    agent_id: `monitor-${index + 1}`,
    source: "custom-office",
    activity: "reading",
    seq: 11 + index,
    event_id: `integration-${index + 1}`,
    timestamp: "2026-10-18T10:00:05Z",
    summary: `Monitoring source ${index + 1}`,
    data: { display_name: `Feed monitor ${index + 1}` },
  }));
  const emit = async (events: object[]) =>
    page.evaluate((events) => {
      for (const event of events)
        (
          window as unknown as { __officeEmit: (event: unknown) => void }
        ).__officeEmit(event);
    }, events);
  await emit(actors.slice(0, 3));
  await page
    .getByRole("button", {
      name: "Feed monitor 1: Reading. Inspect agent",
      exact: true,
    })
    .click();
  await emit([actors[3]]);
  await expect(
    page.getByText("Integrations 4–4 of 4", { exact: true }),
  ).toBeVisible();
  await expect(summaryBubble(page, "Monitoring source 4")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Previous Integrations page", exact: true })
    .click();
  await emit([
    {
      ...actors[3],
      seq: 15,
      event_id: "integration-progress",
      summary: "Monitoring another source section",
    },
  ]);
  await expect(
    page.getByText("Integrations 1–3 of 4", { exact: true }),
  ).toBeVisible();
  await expect(summaryBubble(page, "Monitoring source 1")).toHaveCount(1);
  await expect(
    summaryBubble(page, "Monitoring another source section"),
  ).toHaveCount(0);
});

test("named Task specialists page separately from external integrations and preserve actual identity", async ({
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
    page.getByText("Task specialists 5–8 of 8", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Previous Task specialists page",
      exact: true,
    })
    .click();
  await expect(
    page.getByText("Task specialists 1–4 of 8", { exact: true }),
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
      name: "Next Task specialists page",
      exact: true,
    })
    .click();
  await expect(
    page.getByText("Task specialists 5–8 of 8", { exact: true }),
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
  await page.getByRole("button", { name: "Agents", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Search agents" })
    .fill("Shader specialist 8");
  await page
    .locator(".agent-list .agent-row")
    .filter({ hasText: "Shader specialist 8" })
    .click();
  await page.getByRole("button", { name: "Office", exact: true }).click();
  const bubble = summaryBubble(page, "Checking shader validation");
  await expect(bubble).toHaveAttribute("title", /Shader specialist 8/);
  await page
    .getByRole("button", {
      name: "Shader specialist 8: Reading. Inspect agent",
    })
    .click();
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(
    inspector.getByText("Checking shader validation", { exact: true }),
  ).toBeVisible();
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
    page.getByText("Task specialists 1–4 of 8", { exact: true }),
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

test("Research task specialists retain names, private files, inherited models and activity on the fifth desk", async ({
  page,
}) => {
  const fifth = "specialist:run-fixture:research-5";
  await fixture(
    page,
    {
      agent_model_configs: {
        data_analyst: {
          provider: "zai",
          model: "citation-model",
          reasoning_effort: "high",
        },
      },
    },
    [
      {
        artifact_id: "research-own",
        name: "citation-index.json",
        media_type: "application/json",
        run_id: runId,
        kr_id: "KR1",
        size: 500,
        scope: JSON.stringify(["research-wp5", 0, fifth]),
      },
      {
        artifact_id: "research-sibling",
        name: "sibling-private.json",
        media_type: "application/json",
        run_id: runId,
        kr_id: "KR1",
        size: 300,
        scope: JSON.stringify([
          "research-wp1",
          0,
          "specialist:run-fixture:research-1",
        ]),
      },
      {
        artifact_id: "research-legacy",
        name: "legacy-unassigned.json",
        media_type: "application/json",
        run_id: runId,
        kr_id: "KR1",
        size: 300,
      },
    ],
  );
  await page.evaluate(() => {
    const emit = (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit;
    for (let index = 1; index <= 5; index++)
      emit({
        event_id: `research-${index}`,
        seq: 50 + index,
        source: "harness",
        agent_id: `specialist:run-fixture:research-${index}`,
        run_id: "run-fixture",
        kr_id: "KR1",
        activity: "completed",
        summary: `Validated research source set ${index}`,
        data: {
          agent_type: "research_specialist",
          display_name: `Citation specialist ${index}`,
          parent_agent_id: "research_head",
          department: "research",
          model_parent: "data_analyst",
        },
        timestamp: "2026-10-20T10:00:00Z",
      });
    emit({
      event_id: "research-external",
      seq: 56,
      source: "custom",
      agent_id: "specialist:run-fixture:research-5",
      run_id: "run-fixture",
      activity: "reading",
      summary: "External citation monitor",
      data: {
        agent_type: "research_specialist",
        display_name: "External Research mirror",
        parent_agent_id: "research_head",
        model_parent: "data_analyst",
      },
      timestamp: "2026-10-20T10:00:00Z",
    });
  });
  await expect(
    page.getByText("Task specialists 5–5 of 5", { exact: true }),
  ).toBeVisible();
  await eventBubble(page, fifth).click();
  const inspector = page.getByRole("complementary", { name: "Selected agent" });
  await expect(
    inspector.getByRole("heading", {
      name: "Citation specialist 5",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    inspector.locator(".detail-row").filter({ hasText: "Department" }),
  ).toContainText("Research");
  await expect(
    inspector.locator(".detail-row").filter({ hasText: "Parent" }),
  ).toContainText("Research lead");
  await expect(inspector.locator(".agent-model-note")).toContainText(
    "citation-model",
  );
  await expect(inspector.locator(".agent-model-note")).toContainText(
    "Inherited from Data analyst",
  );
  await page.getByRole("tab", { name: /^Files/ }).click();
  await expect(
    inspector.getByText("citation-index.json", { exact: true }),
  ).toBeVisible();
  await expect(
    inspector.getByText("sibling-private.json", { exact: true }),
  ).toHaveCount(0);
  await expect(
    inspector.getByText("legacy-unassigned.json", { exact: true }),
  ).toHaveCount(0);
  await page.evaluate(() =>
    (
      window as unknown as { __officeEmit: (event: unknown) => void }
    ).__officeEmit({
      event_id: "research-bare-progress",
      seq: 57,
      source: "harness",
      agent_id: "specialist:run-fixture:research-5",
      run_id: "run-fixture",
      kr_id: "KR1",
      activity: "reading",
      summary: "Checking the final citation mapping",
      data: { tool_name: "read_artifact" },
      timestamp: "2026-10-20T10:00:01Z",
    }),
  );
  await expect(eventBubble(page, fifth)).toHaveAttribute(
    "title",
    /Citation specialist 5.*Checking the final citation mapping/,
  );
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await expect(
    inspector.getByText("Checking the final citation mapping", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "External Research mirror: Reading. Inspect agent",
    })
    .click();
  await expect(
    inspector.locator(".detail-row").filter({ hasText: "Department" }),
  ).toContainText("Integrations");
  await expect(inspector.locator(".agent-model-note")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Send guidance to agent" }),
  ).toBeDisabled();
  await page.route("**/api/office", (route) =>
    route.fulfill({
      json: {
        agents: Array.from({ length: 5 }, (_, index) => ({
          event_id: `research-snapshot-${index}`,
          seq: 51 + index,
          source: "harness",
          agent_id: `specialist:run-fixture:research-${index + 1}`,
          run_id: runId,
          kr_id: "KR1",
          activity: "completed",
          summary: `Saved research snapshot ${index + 1}`,
          data: {
            agent_type: "research_specialist",
            display_name: `Citation specialist ${index + 1}`,
            parent_agent_id: "research_head",
            department: "research",
            model_parent: "data_analyst",
          },
          timestamp: "2026-10-20T10:00:02Z",
        })),
        cursor: 57,
        generation: "fixture-generation",
      },
    }),
  );
  await page.reload();
  await expect(
    page.getByText("Task specialists 5–5 of 5", { exact: true }),
  ).toBeVisible();
  await eventBubble(page, fifth).click();
  await expect(
    inspector.getByRole("heading", {
      name: "Citation specialist 5",
      exact: true,
    }),
  ).toBeVisible();
  await expect(inspector.locator(".agent-model-note")).toContainText(
    "Inherited from Data analyst",
  );
});

test("all unlimited budgets show queued automatic continuation without a review prompt, while operator pauses remain explicit", async ({
  page,
}) => {
  await fixture(page, {
    status: "queued",
    limits: {
      max_model_calls: null,
      worker_model_calls: null,
      max_tool_calls: null,
    },
    review: {
      interrupt_id: "stale-quality-review",
      kind: "blocked",
      reason: "Old quality failure",
    },
    continuation: {
      attempt: 3,
      reason: "Provider rate limit; saved progress will be retried",
      scheduled_at: "2026-10-20T10:00:00Z",
    },
    next_attempt_at: "2026-10-20T10:05:00Z",
    automatic_cycles: 2,
    autonomous_failures: 1,
  });
  const banner = page.getByRole("status", {
    name: "Autonomous continuation",
    exact: true,
  });
  await expect(
    banner.getByText("Automatic continuation scheduled", { exact: true }),
  ).toBeVisible();
  await expect(banner).toContainText("Provider rate limit");
  await expect(banner.locator("time")).toHaveAttribute(
    "datetime",
    "2026-10-20T10:05:00Z",
  );
  await expect(banner).toContainText("2 cycles · 3 continuations");
  await expect(page.locator(".review-banner")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Review and resume mission" }),
  ).toBeDisabled();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Cancel mission" }),
  ).toBeEnabled();
  await page.route(`**/api/runs/${runId}`, (route) =>
    route.fulfill({
      json: {
        ...initialRun,
        status: "review",
        limits: {
          max_model_calls: null,
          worker_model_calls: null,
          max_tool_calls: null,
        },
        review: {
          interrupt_id: "legacy-auto",
          kind: "blocked",
          reason: "Worker repair pending",
        },
      },
    }),
  );
  await page.reload();
  await expect(banner).toContainText("Autonomous recovery pending");
  await expect(page.locator(".review-banner")).toHaveCount(0);
  await page.route(`**/api/runs/${runId}`, (route) =>
    route.fulfill({
      json: {
        ...initialRun,
        status: "paused",
        limits: {
          max_model_calls: null,
          worker_model_calls: null,
          max_tool_calls: null,
        },
        review: {
          interrupt_id: "manual",
          kind: "manual_pause",
          reason: "Operator paused",
          allowed_actions: ["continue", "abort"],
        },
      },
    }),
  );
  await page.reload();
  await expect(banner).toHaveCount(0);
  await expect(page.locator(".review-banner")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review and resume mission" }),
  ).toBeEnabled();
  await page.route(`**/api/runs/${runId}`, (route) =>
    route.fulfill({
      json: {
        ...initialRun,
        status: "failed",
        limits: {
          max_model_calls: null,
          worker_model_calls: null,
          max_tool_calls: null,
        },
        error:
          "An interrupted host command has an unknown outcome; automatic replay is unsafe.",
      },
    }),
  );
  await page.reload();
  await expect(page.locator(".failure-banner")).toContainText(
    "Unresolved command effects must be reconciled",
  );
  await expect(page.locator(".failure-banner")).not.toContainText(
    "may require review",
  );
  await expect(
    page.getByRole("button", { name: "Retry mission", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".review-banner")).toHaveCount(0);
  await expect(banner).toHaveCount(0);
});
