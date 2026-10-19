# SPOC agent office

Local React 19 / TypeScript / Canvas 2D client for the durable SPOC runtime. The office artwork is original code-native geometry and sprites; no assets are copied from Pixel Agents. Fonts are bundled, so the UI makes no third-party requests at runtime.

## Development

Use Node 24 and npm. Run the API on `127.0.0.1:8000`, then:

```sh
npm ci
npm run dev
```

Vite serves `http://127.0.0.1:5173` and proxies `/api` to the API. To serve the built office from FastAPI, run `npm run build` before starting the API. `dist/` is generated and should not be committed.

## Verification

```sh
npm run check
npm run format:check
npm test
npm run build
npx playwright install chromium
npm run e2e
```

Browser tests use local API and event-stream fixtures and never call an LLM. They cover mission creation, constitution submission, guidance, pause/resume/cancel, event projection and reconnection, source isolation, artifact links, keyboard selection, reduced motion, and mobile navigation. Desktop and mobile screenshots are emitted to ignored `test-results/`.

## State and integration

`GET /api/office` provides a projection, numeric event cursor, and reset generation. The client consumes named `activity` SSE messages from `/api/events?after=<cursor>&generation=<generation>`, deduplicates sequences, and reconnects from its last applied cursor. Both activity views load persisted, newest-first pages from `/api/events/history`, so reload preserves history. The stream filters by selected mission or all activity; the inspector filters by mission and exact source/agent identity. “Load earlier activity” fetches older pages. Persisted history never changes the live desks or replays handoffs. Per-event subscriptions retain live bursts before the separate 200-event animation buffer truncates them. A connected status reflects the stream connection; office activity always reflects server events. Idle agents are the initial state, with no simulated work.

The eleven fixed internal roles have stable desk positions. Dynamic Engineering specialists and external integrations have separate paged desk areas, and all agents remain available in the searchable list. External agents are keyed by `source:agent_id`, preserving internal identities even when their raw IDs match. The webhook help dialog documents `/api/integrations/events`; incoming external activity does not change internal run records.

The native modal dialogs trap focus and support Escape. Every canvas character has a keyboard-operable button; the list view exposes all statuses as text. Reduced-motion preferences disable continuous canvas animation. On narrow screens the inspector appears below the office, and the strategic pyramid is available through an expandable panel.

Workspace settings include a separate call-budget form below model selection. The mission budget covers all generative requests, including reviews and retries; the per-agent limit caps model turns within an invocation. These workspace defaults apply to new missions and remain independent of per-agent model overrides. Budget and model saves preserve unsaved edits in the other form. Regenesis restores both budget defaults (100 mission requests and 12 agent turns).

The runtime note also reports the server's web-search provider (Exa or Z.AI MCP) and missing configuration. This is read-only, with no credential or provider-selection form. Older API responses without `web_search` show “Not reported.” Set `EXA_API_KEY` on the server to select Exa automatically for Research and Tools R&D search and contents, or use `WEB_SEARCH_PROVIDER` for an explicit override; `EXA_TIMEOUT` defaults to 30 seconds. Exa failures do not trigger a provider fallback. Existing evidence remains stored, and Engineering's direct URL reader is unchanged.

An unavailable individual Exa page is a recoverable tool result, allowing the agent to try another source or use saved evidence. It does not open a review automatically. Provider credentials, quota, service, or response-schema failures remain blockers; their recorded reason and evidence appear through the normal review flow. No page failure triggers URL rewriting or a direct HTTP fallback.

Human reviews start with a brief explanation and plain next-step choices. The primary button names the selected action. Ordinary retries use the current requirements and recorded feedback, with optional additional instructions; policy and clarification reviews require written guidance. Requirements are editable only after selecting that choice. Evidence, gate feedback, attempts, and files remain under a collapsed disclosure. The UI honors the backend's `allowed_actions` and preserves the exact interrupt ID. Legacy reviews use available recorded context; pending dependencies remain separate from failures.

Files are grouped as task outputs, sources, verification logs, submission metadata, and other files. Source retrievals and metadata records do not count as produced task outputs. Historical zero-byte diagnostic logs remain downloadable and are explicitly labeled as empty logs.
