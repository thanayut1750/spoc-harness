# SPOC Harness

Strategic Pyramid and Organization Chart harness: a durable LangGraph runtime with a live, interactive 2D agent office. Submit an objective, inspect its measurable key results, watch departments work, and resolve blockers without losing execution state.

This is a local, single-user application. The API has no login and binds to `127.0.0.1`. Engineering tools run directly on the host with your account's privileges. Constitution checks govern the workflow; they do not create an operating-system sandbox.

## Start locally

Requirements: [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 24+, and Docker Compose or an existing PostgreSQL 18 database. `uv` manages Python 3.12 for this project.

```bash
uv sync --frozen
docker compose up -d --wait
```

Keep your existing `.env` provider configuration. For a new installation, copy `.env.example` to `.env`, then set `OPENAI_API_KEY`. The defaults target Z.AI's Coding Plan endpoint and `glm-5.3-flash`. Process environment variables override `.env`. The legacy spelling `REASIONING_EFFORT` remains accepted; `REASONING_EFFORT` takes precedence.

Set the server's `EXA_API_KEY` to use Exa for web search and page contents. Exa is selected automatically when that key is configured; without it, the harness retains legacy Z.AI MCP search and reading. Set `WEB_SEARCH_PROVIDER=exa` or `zai_mcp` to select explicitly. `EXA_TIMEOUT` defaults to 30 seconds. The office reports the selected provider and whether it is configured; credentials stay on the server.

```bash
uv run spoc migrate
cd frontend
npm ci
npm run build
```

From the repository root, manage the API and worker together:

```bash
uv run spoc start
uv run spoc stop
uv run spoc restart
```

`start` runs both services in the background and reuses verified services already running. `stop` requests graceful shutdown; `restart` stops both before starting them with the current `.env` and process environment. Saved runs, checkpoints, artifacts and credentials are preserved. These commands do not start PostgreSQL, run migrations, or build the frontend. Logs are in `.harness/api.log` and `.harness/worker.log` (or your `SPOC_DATA_DIR`).

Use `--timeout 30` to allow more startup/shutdown time. Shutdown timeout leaves the remaining service recorded and reports an error; `--force` on `stop` or `restart` explicitly permits termination after that wait. Force termination can leave host commands running or their effects uncertain. Governed missions retain interrupted-command recovery review; autonomous missions reconcile supervisor receipts before continuing. Linux process identity checks protect against stale or reused PID files, and concurrent lifecycle commands are serialized. `spoc serve` and `spoc worker` remain available as foreground commands for separate terminals or an external service manager.

Open [the office](http://127.0.0.1:8000). The API reference is at [local API docs](http://127.0.0.1:8000/docs).

Database defaults are `postgresql://spoc:spoc@127.0.0.1:5432/spoc`. Change both `SPOC_POSTGRES_PASSWORD` for Compose and `DATABASE_URL` if you choose another password. Existing Postgres installations only need `DATABASE_URL`; Docker is not required for the API or worker.

## Use the harness

Create an objective in the office or through the CLI:

```bash
uv run spoc run "Research an API design and implement a verified Python prototype"
uv run spoc status
uv run spoc status RUN_ID
uv run spoc pause RUN_ID
uv run spoc cancel RUN_ID
uv run spoc retry RUN_ID
uv run spoc doctor
```

Use `spoc run --workspace /absolute/project/path` to select an existing project. Otherwise, each KR writes to its own local workspace under `.harness/workspaces/`. Use `--constitution policy.json` to supply a mission, prohibited actions, compliance rules, and `max_revision_loops`.

The office shows the objective/KR hierarchy on the left, actual agent activity in department rooms, and selected-agent details on the right. The latest recorded event appears above each agent, including Research and Engineering specialists and connected integrations. New agents bring their desk page into view without changing inspector selection. Error-status agents hide their bubbles while keeping recorded history available in the inspector. Select an agent to inspect its full activity history, evidence, tool logs, and gate feedback. Human guidance is consumed at the next applicable agent boundary. Pause waits for a safe graph boundary; cancel also terminates active host commands.

In governed mode, ordinary blockers in the full workflow receive one automatic executive replan per run. Fast-track and departmental work stop for review after their bounded retry allowance. Constitution violations pause governed missions for review. With all three call caps unlimited, routine blockers and rejected results trigger saved continuation or compliant replanning without a human decision; the constitution and acceptance criteria remain mandatory. Explicit manual pauses stay paused. Governed review actions provide context, revise a KR, explicitly retry an interrupted command, or abort. Revising a KR creates a new version and invalidates dependent approvals. Use the review drawer or `spoc resume --help` to resume the recorded interrupt.

The review panel starts with a short explanation and plain choices: retry the task, change its requirements, or stop the run. A normal retry preserves the current requirements and recorded feedback; extra instructions are optional. Rule violations and clarification requests require written guidance. The primary button names the action it will take.

An unexpected execution failure shows its error and a **Retry mission** action. Retry continues the same saved checkpoint, preserving the original request, model selections, budgets, evidence and failure history. Governed missions retain interrupted-command review. Autonomous recovery uses supervised receipts or truthful interrupted outcomes. An explicit autonomous retry can re-enter the saved harness coordinator after a finished failure while retaining approved outcomes. A governed finished graph, or a graph without a supported restart path, needs a new mission.

Expand **Review evidence and history** for the mission, blocked KR and acceptance criteria, gate feedback, recorded attempts, and files. Pending dependent KRs appear separately. Older runs recover the available summaries and evidence without rewriting their saved interrupt; unavailable history is labeled explicitly.

## Execution and persistence

- A checkpointed `TriageRouter` classifies the request with TypeSafe Jev before planning. `FAST_TRACK` uses one specialist with no strategic or tactical planning calls. `DEPARTMENTAL` uses one department lead and subgraph. Both use one final semantic KR review per attempt and at most one rework within that cycle. Governed optimized missions then stop for review; autonomous missions schedule another planning cycle if needed. Pure engineering work does not start Research. `FULL_PYRAMID` retains both departments and strategic decomposition. Missing credentials, uncertain decisions, or an eight-second classifier timeout retain the full workflow.
- The full workflow plans and validates 1–3 objectives containing at most nine KRs. It dispatches dependency-ready work with at most one KR per department and two work packages active overall.
- Research and Engineering subgraphs plan bounded specialist assignments. Workers use LangChain `create_agent` with role-scoped tools. Only validated dependency artifacts and bounded summaries cross graph boundaries; parent transcripts never become worker history.
- Gates check evidence, constitution compliance, every criterion, and a minimum score of 0.8. Worker confidence cannot approve a KR. Full-pyramid work uses the constitution's rework limit (two by default); optimized modes cap that limit at one. Their worker handoff performs structural validation, leaving the semantic assessment to the final KR gate.
- Postgres stores application state, jobs, event projections, checkpoints, and artifact metadata. Local disk holds immutable artifact contents and full command logs.
- Completed tool operations are reused on replay. Governed missions ask before retrying a host command with unknown effects. Autonomous missions reconcile durable command receipts, return truthful interrupted/uncertain results for inspection, and continue without blindly replaying the command.
- A global worker lock and renewable leases prevent overlapping runs. Only one run executes at a time; departments can work concurrently within it.

### Dynamic specialists and Tools R&D

Research and Engineering leads can define task-specific specialists in their tactical plans, with a name, focused instructions, and an optional subset of their base role's execution tools. Artifact reading, output writing, and blocker reporting remain available so a restricted specialist can submit its work. A web app can receive visualization and accessibility specialists; a research task can receive source-mapping and analysis specialists. Each has a stable mission-scoped identity and private history, survives checkpoint recovery, and inherits the saved model selection of its base role. Market researchers can search, read sources, and write/publish artifacts; Data analysts can also execute commands and tested mission tools. Existing limits still apply within each cycle: 1–4 ordered work packages per KR, shared run budgets, worker deadlines, and acceptance gates. Fast-track work continues directly to its single worker.

Only **Planner** and **Engineering lead** can call **Tools R&D lead**. They can request research, a new tool, or an analysis of which is needed. This capability is enforced by the server and by the tools exposed to each agent. Workers, Research, Executive, reviewers, and Tools R&D itself cannot call this lead. Routine tasks do not invoke R&D automatically.

Tools R&D can research a capability and return a substantive report, or create a Python tool that reads JSON from stdin and writes one JSON value to stdout. Registration validates its input schema and runs a representative example in a separate, journaled process. Successful registrations preserve immutable source, schema, and test evidence in the mission's artifacts. Engineering workers, Research data analysts, and the two planning agents can invoke the exact registered tool ID with validated arguments. Generated code is never imported into the harness process. Tools are scoped to their mission and are removed by Regenesis. Governed missions allow at most two R&D consultations per planning invocation and twelve registered tool versions per mission. Autonomous missions retain all immutable versions without those lifetime caps. Their tool discovery uses bounded pages with complete input schemas, so a growing registry does not fill agent context. Tools R&D can reuse tested tools when consulted in autonomous mode; its caller restriction remains unchanged.

Review evidence includes the specialist's assignment, verified public R&D delegation, and successful tool invocations. Assignment metadata and tool support files cannot replace substantive task output. Parallel R&D consultations use separate managed workspaces.

The office shows Tools R&D and named Research and Engineering specialists separately from external integrations. Extra agents use paged desks and remain searchable. Select a specialist to inspect its real activity, files, inherited model, or send it guidance. Tools R&D has no direct UI launch action; its model remains configurable in Settings.

The Z.AI adapter preserves provider reasoning fields within private model history for tool-roundtrip correctness. Office events expose activity, outputs, and evidence rather than raw provider reasoning. Structured responses use JSON-object mode and Pydantic validation, with one schema repair attempt. Transient model requests have bounded retries and count toward the global call budget.

An empty or truncated worker response receives one continuation within its existing private context and call budget. If it remains incomplete, the worker reports an execution failure instead of creating an empty submission. Tool records supply the artifact manifest even when the model omits IDs from its final answer. Large research responses are stored in full and shown to workers in bounded pages. Missing output is a quality failure; a compliance breach triggers governed review or an automatic compliant replan in autonomous mode. Requirements and acceptance gates are never waived.

Files are grouped as task outputs, sources, verification logs, and submission metadata. A command always records its exit status, duration, command, and output references in a receipt. Only nonempty stdout/stderr become downloadable output artifacts, so a successful silent command does not generate empty task files.

Immutable earlier file versions and failed checks remain available for inspection. Submission evidence uses current file revisions and final checks, so a corrected file does not remain rejected because of an obsolete broken snapshot.

Workers register requested text output with `write_file`, or use `publish_file` to snapshot a file created or edited by a host command. Publication preserves the exact bytes and records the current assignment, integrity hash and downloadable artifact ID without regenerating its content. Empty, binary and oversized files receive a tool error. Verification logs alone do not replace the requested output.

Research and Tools R&D use the selected web provider for search and page contents, including R&D consulted for an Engineering KR. Exa uses the dedicated `EXA_API_KEY`. Legacy Z.AI MCP uses `ZAI_API_KEY`, or the configured Z.AI endpoint's `OPENAI_API_KEY` when no separate Z.AI key is set; the key needs the relevant tool entitlement. Native OpenAI credentials are not reused for MCP.

An individual page that Exa cannot crawl, cannot find, or returns without readable content produces a recoverable tool error. The agent can try another URL or reuse saved evidence within its existing limits. Credential, quota, provider-service, and malformed-response failures remain blockers. An unavailable page does not trigger a direct HTTP fallback, URL rewriting, or a switch to Z.AI or sample results. Saved research artifacts and operation evidence remain available after changing providers. `spoc doctor --live` makes real provider requests and consumes provider quota.

Engineering workers can read reference URLs directly with a bounded HTTP `read_web_page` tool while remaining in Engineering. `read_artifact` accepts only IDs returned by tools, not URLs or file paths. Expected resource/input errors are recorded as actionable tool results so the model can correct them. Missing run records, database failures, unknown command effects and programming errors are never presented as successful tool output.

Default configurable limits: 100 generative model requests and 200 tool calls per run, 12 agent model turns per invocation, a one-hour (3600-second) timeout covering each worker invocation and output extraction, and a 300-second command timeout. Per-run API overrides use `limits.worker_timeout` with a maximum of 3600 seconds; saved runs keep their recorded limits unless explicitly updated by an operator. Tactical packages are critical by default. A lead may mark an enrichment step optional (`critical=false`); a timeout or ordinary blocker then returns an explicitly incomplete fallback with partial evidence, allowing other work to continue. Fallbacks cannot approve work or waive acceptance criteria. Governed missions retain their budget and review gates. With all three call budgets unlimited, deadlines bound work sessions rather than the mission: private checkpoints resume automatically, blockers use delayed retries or compliant replanning, and interrupted commands are reconciled. Manual pause/cancel always take priority. The example healthcare/privacy and dollar-budget policies from the initial proposal are not hardcoded. Configure a constitution appropriate to each objective.

### Model settings and Regenesis

Open **Settings → Model** to configure a provider, model ID, and reasoning effort for all agents or a particular agent. Provider connections and credentials come from server environment variables; the UI never accepts or exposes API keys. The configured endpoint uses existing `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `MAIN_MODEL`. Optional separate connections use `ZAI_API_KEY`, `SPOC_OPENAI_API_KEY`, or the `SPOC_COMPATIBLE_*` variables in `.env.example`. Use tool-capable models and reasoning options supported by the selected model. Native OpenAI uses Chat Completions; models requiring Responses tool calling need a different adapter.

The **Call budgets** section saves workspace defaults for **Model calls per mission** (1–10,000), **Agent model turns per invocation** (1–100), and **Tool calls per mission** (1–100,000). Each has an independent **No limit** option, represented by JSON `null` in `max_model_calls`, `worker_model_calls`, or `max_tool_calls`. Removing a model cap leaves any finite tool cap in effect; removing a tool cap leaves finite model caps in effect. Selecting **No limit for all three fields** enables autonomous execution without routine human review. Session/command deadlines and bounded review attempts still protect individual cycles; they schedule another saved cycle instead of imposing an overall mission duration or revision cap. Partial unlimited selections retain governed behavior. The mission model budget covers generative requests across all agents, including extraction, reviews, repairs, and retries; TypeSafe triage is separate. Tool calls share a mission-wide counter across built-in agents, dynamic specialists, and Tools R&D. New office and CLI missions inherit these defaults. Explicit per-run `limits` values, including `null`, take precedence. Regenesis restores the finite startup defaults of 100 model calls, 12 agent turns, and 200 tool calls.

Existing missions retain their saved limits. With a paused, review, or failed mission selected, **Apply saved budgets to this mission** explicitly copies the saved workspace call budgets into that mission. The action stays disabled until budget edits are saved. The UI shows its current limits and usage; the HTTP update preserves checkpoints, review, and counters. Once all three caps are unlimited, the worker automatically adopts routine review missions and continues from saved progress; explicit manual pauses remain paused. Running or queued work and completed or cancelled missions cannot be updated this way, and the server rejects updates while a worker still owns execution. Finite missions retain normal review controls. Explicitly paused and terminal failed missions retain their separate resume/retry controls. The API is `PUT /api/runs/{id}/budgets` with one or more of the three budget keys; omitted keys preserve that mission’s existing limits.

Saved selections are copied into each new run. Existing runs retain their original selection, including agent overrides. Per-run API overrides use `model_config` and `agent_model_configs`. Jev remains a separate decision model configured with `TYPESAFE_API_KEY` and `TYPESAFE_MODEL`.

**Settings → Regenesis** resets the application to its startup defaults after typing `REGENESIS`. The callable API is `POST /api/regenesis` with `{"confirmation":"REGENESIS"}`; the CLI equivalent is `uv run spoc regenesis --confirm REGENESIS`. It cancels unfinished runs, waits for exclusive worker ownership, removes managed artifact/workspace directories, and clears application records, events, operation journals, settings, LangGraph checkpoints and store data. The database schema remains usable. `.env`, application code, database infrastructure and user-selected external workspaces remain intact; arbitrary host command effects outside managed directories cannot be undone. Use a database dedicated to this harness because its LangGraph checkpoint/store tables are reset too. Browser state and event cursors reload after reset.

`MODEL_MAX_TOKENS` defaults to 32768 and `MODEL_TIMEOUT` to 300 seconds. The token allowance includes provider thinking and visible output; an 8192-token cap can end a long reasoning turn before any answer is produced. Existing explicit environment settings still take precedence.

## Deterministic demonstration

Set `HARNESS_TEST_MODE=true` in both API and worker environments to use clearly labeled research fixtures and small, actual local Python verification commands. Keep Postgres enabled: separate API and worker processes still require shared storage. This mode makes no model or research network calls and does not represent its fixture data as live research.

`storage_backend=memory` is reserved for an explicitly injected, single-process test backend. It is not durable and cannot share state across separate processes.

## External activity webhooks

External activity is display-only. It cannot approve KRs, resolve reviews, or update internal execution status. Duplicate `(source,event_id)` pairs return the original event.

```bash
curl http://127.0.0.1:8000/api/integrations/events \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"example-1","source":"my-agent","agent_id":"helper","activity":"reading","summary":"Reading project documentation"}'
```

Activity values are `idle`, `planning`, `reading`, `writing`, `executing`, `reviewing`, `waiting`, `completed`, and `error`. Optional fields include `run_id`, `kr_id`, `timestamp`, and bounded display `data`. The office snapshots its current event cursor and reconnects to persisted SSE events after that cursor.

Activity appears directly above the agents instead of in a separate stream dialog. Each label shows that agent's latest recorded event and updates from the live stream; the saved office projection restores it after a refresh. The inspector's **Activity** tab loads saved history and merges live events into it; use **Load earlier activity** to page backward. Inspector activity follows the actual agent and selected mission; external integrations keep their separate source identity. Historical events leave the current office positions and handoffs intact. Public model-work, file-read, delegation, and failure events keep activity visible as agents work.

## API

| Route | Purpose |
| --- | --- |
| `POST /api/runs` | Queue objective, optional workspace, constitution, and limits |
| `GET /api/runs`, `GET /api/runs/{id}` | Run history and current progress |
| `POST /api/runs/{id}/pause`, `/resume`, `/cancel`, `/retry` | Lifecycle and saved-checkpoint recovery commands |
| `POST /api/runs/{id}/notes` | Queue targeted human guidance |
| `GET /api/settings`, `PUT /api/settings/model` | Read public provider settings and save model defaults |
| `PUT /api/settings/budgets` | Save workspace model-call, agent-turn, and tool-call defaults for new missions |
| `PUT /api/runs/{id}/budgets` | Explicitly update a stopped mission’s call limits without resuming or resetting usage |
| `PUT`, `DELETE /api/settings/agents/{agent_id}` | Set an agent override or return it to the default |
| `POST /api/regenesis` | Confirmed reset of all harness-managed data |
| `GET /api/office`, `GET /api/events?after=CURSOR` | Snapshot and SSE event replay |
| `GET /api/events/history` | Newest-first saved activity, with `run_id`, `agent_id`, `source`, exclusive `before`, and bounded `limit` filters |
| `GET /api/runs/{id}/artifacts`, `GET /api/artifacts/{id}` | Evidence and files |
| `POST /api/integrations/events` | External display activity |
| `GET /healthz`, `GET /readyz` | Liveness and database readiness |

Use `Idempotency-Key` for run submission and lifecycle commands. Reusing a key with different content returns a conflict. A resume request must match the current `interrupt_id` and allowed review action. `.env` and provider credentials are never returned by configuration diagnostics.

## Development and tests

```bash
uv run ruff check .
uv run pytest -m 'not live'
cd frontend
npm run check
npm test
npm run build
npx playwright install chromium
npm run e2e
```

Set `SPOC_TEST_DATABASE_URL` to a Postgres administrative connection to enable integration tests. The test role needs `CREATEDB`: each integration test creates and drops its own isolated temporary database. Without the connection, those tests explicitly skip; unit tests use scripted services and injected in-memory storage. Tests cover hierarchy isolation, concurrent scheduling, revisions, constitution escalation, restart-safe human review, command replay/cancellation, event replay, webhooks, and UI interactions.

For frontend development use `npm run dev`; Vite proxies `/api` to the local backend. Python modules are under `src/org_harness/`; the independent UI is under `frontend/`.

## Operations

Apply `spoc migrate` before starting a new deployment. Migrations are explicit and are not automatically run by API startup. Use `spoc doctor`, `/readyz`, and worker logs to diagnose configuration or database failures. Worker error logs report error categories rather than provider response bodies.

Back up Postgres and `.harness/artifacts/` together. Restore both, reapply pending migrations, and restart the worker; checkpoint state and the operation journal determine recovery. Never delete an unknown-operation record merely to force a command to rerun. In governed mode, retain its review and authorize any retry explicitly. Autonomous mode recovers the supervisor receipt or records a truthful interrupted outcome for inspection; it does not blindly repeat the original command.

LangSmith tracing is optional and disabled by default. Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` to opt in. Local events and execution do not depend on a LangSmith account.

## Contributing

Use feature branches and reviewable pull requests rather than pushing changes directly to `main`. Keep secrets and generated workspaces out of commits. Run the relevant tests and both build checks before requesting review. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow.

The office metaphor is inspired by [Pixel Agents](https://github.com/pixel-agents-hq/pixel-agents). This project uses an independent renderer and original code-generated assets.
