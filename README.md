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

```bash
uv run spoc migrate
cd frontend
npm ci
npm run build
```

From the repository root, start the API and worker in separate terminals:

```bash
uv run spoc serve
```

```bash
uv run spoc worker
```

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
uv run spoc doctor
```

Use `spoc run --workspace /absolute/project/path` to select an existing project. Otherwise, each KR writes to its own local workspace under `.harness/workspaces/`. Use `--constitution policy.json` to supply a mission, prohibited actions, compliance rules, and `max_revision_loops`.

The office shows the objective/KR hierarchy on the left, actual agent activity in department rooms, and selected-agent details on the right. Select a character to inspect its work, evidence, tool logs, and gate feedback. Human guidance is consumed at the next applicable agent boundary. Pause waits for a safe graph boundary; cancel also terminates active host commands.

Ordinary blockers receive one automatic executive replan per run. Constitution violations pause immediately for review. Review actions provide context, revise a KR, explicitly retry an interrupted command, or abort. Revising a KR creates a new version and invalidates dependent approvals. Use the review drawer or `spoc resume --help` to resume the recorded interrupt.

## Execution and persistence

- The root `StateGraph` plans and validates 1–3 objectives containing at most nine KRs. It dispatches dependency-ready work with at most one KR per department and two work packages active overall.
- Research and Engineering subgraphs plan bounded specialist assignments. Workers use LangChain `create_agent` with role-scoped tools. Only validated dependency artifacts and bounded summaries cross graph boundaries; parent transcripts never become worker history.
- Tactical and department gates check evidence, constitution compliance, every criterion, and a minimum score of 0.8. Worker confidence cannot approve a KR. Two shared rework cycles are available after the initial attempt.
- Postgres stores application state, jobs, event projections, checkpoints, and artifact metadata. Local disk holds immutable artifact contents and full command logs.
- Completed tool operations are reused on replay. If a host command was running when execution was interrupted, its result is treated as unknown and reviewed before retry. No claim of exactly-once arbitrary shell execution is made.
- A global worker lock and renewable leases prevent overlapping runs. Only one run executes at a time; departments can work concurrently within it.

The Z.AI adapter preserves provider reasoning fields within private model history for tool-roundtrip correctness. Office events expose activity, outputs, and evidence rather than raw provider reasoning. Structured responses use JSON-object mode and Pydantic validation, with one schema repair attempt. Transient model requests have bounded retries and count toward the global call budget.

Research uses Z.AI Search and Reader MCP tools with the configured key. Access depends on the key's tool entitlement; unavailable tools report a blocker rather than returning sample results. `spoc doctor --live` makes real provider requests and consumes provider quota.

Default configurable limits: 100 model calls and 200 tool calls per run, 12 model calls per worker invocation, and a 300-second command timeout. The example healthcare/privacy and dollar-budget policies from the initial proposal are not hardcoded. Configure a constitution appropriate to each objective.

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

## API

| Route | Purpose |
| --- | --- |
| `POST /api/runs` | Queue objective, optional workspace, constitution, and limits |
| `GET /api/runs`, `GET /api/runs/{id}` | Run history and current progress |
| `POST /api/runs/{id}/pause`, `/resume`, `/cancel` | Lifecycle commands |
| `POST /api/runs/{id}/notes` | Queue targeted human guidance |
| `GET /api/office`, `GET /api/events?after=CURSOR` | Snapshot and SSE event replay |
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

Back up Postgres and `.harness/artifacts/` together. Restore both, reapply pending migrations, and restart the worker; checkpoint state and the operation journal determine recovery. Never delete an unknown-operation record merely to force a command to rerun. Keep its review record and authorize the retry explicitly.

LangSmith tracing is optional and disabled by default. Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` to opt in. Local events and execution do not depend on a LangSmith account.

## Contributing

Use feature branches and reviewable pull requests rather than pushing changes directly to `main`. Keep secrets and generated workspaces out of commits. Run the relevant tests and both build checks before requesting review. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow.

The office metaphor is inspired by [Pixel Agents](https://github.com/pixel-agents-hq/pixel-agents). This project uses an independent renderer and original code-generated assets.
