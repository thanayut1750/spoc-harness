import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import type { Artifact, Run } from "../src/types";
const runId = "run-fixture";
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
  let run: Run = { ...initialRun, ...overrides };
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
        },
      });
    if (path === "/api/runs" && method === "GET")
      return route.fulfill({ json: [run] });
    if (path === "/api/runs" && method === "POST") {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
      run = { ...run, user_request: body.user_request, status: "queued" };
      return route.fulfill({
        status: 201,
        json: { run_id: runId, status: "queued" },
      });
    }
    if (path === `/api/runs/${runId}`) return route.fulfill({ json: run });
    if (path.endsWith("/artifacts")) return route.fulfill({ json: files });
    if (method === "POST") {
      const body = route.request().postDataJSON();
      requests.push({ path, body });
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
  await page.getByRole("button", { name: "Apply decision" }).click();
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
  await page
    .getByRole("combobox", { name: "Decision", exact: true })
    .selectOption("revise_kr");
  await page
    .getByRole("combobox", { name: "Key result", exact: true })
    .selectOption("KR2");
  await page.getByLabel("Revised description").fill("Build a tested local API");
  await page
    .getByLabel("Acceptance criteria, one per line")
    .fill("Unit tests pass\nAPI responds locally");
  await page.getByRole("button", { name: "Apply decision" }).click();
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
    dialog.getByText("Build a useful planning tool with cited evidence"),
  ).toBeVisible();
  await expect(
    dialog.getByText("The worker produced no inventory.", { exact: true }),
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
  await expect(
    dialog.getByRole("option", { name: "Continue execution", exact: true }),
  ).toHaveCount(0);
  await expect(dialog.getByText("WHAT HAPPENS NEXT")).toBeVisible();
  await expect(dialog.getByText("1 / 1", { exact: true })).toBeVisible();
  await page.screenshot({
    path: "test-results/review-context-desktop.png",
    fullPage: true,
  });
});
