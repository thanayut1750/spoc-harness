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

`GET /api/office` provides a projection, numeric event cursor, and reset generation. The client consumes named `activity` SSE messages from `/api/events?after=<cursor>&generation=<generation>`, deduplicates sequences, and reconnects from its last applied cursor. Above each agent, an event bubble shows the agent's name and latest recorded summary from that projection, including completed work. Status colors and the accessible full event label identify the recorded activity. Initial idle placeholders have no event bubble. Bubbles automatically hide when the latest event or displayed avatar is in the error/Needs attention state; the avatar, inspector, and full activity history remain available. A later healthy event restores the bubble. Otherwise labels retain the actual recorded event even when a mission has paused or ended. They update live and survive refresh without depending on the 200-event handoff animation buffer. There is no separate Activity stream dialog.

The inspector loads persisted, newest-first pages from `/api/events/history`, filtered by selected mission and exact source/agent identity. “Load earlier activity” fetches older pages. Persisted history never changes the live desks or replays handoffs. Per-event subscriptions retain live bursts before the animation buffer truncates them. A connected status reflects the stream connection; office activity always reflects server events. Idle agents are the initial state, with no simulated work.

The eleven fixed internal roles have stable desk positions. Dynamic Engineering specialists and external integrations have separate paged desk areas, and all agents remain available in the searchable list. When a new non-error agent arrives, its desk page comes into view automatically, including agents first observed after completion. Initial projections keep the explicitly selected agent visible, or prefer working agents and then the newest healthy event. Explicit selection opens that agent's page; ordinary progress events do not override manual paging. External agents use encoded source/raw-agent-ID tuples, preserving distinct identities even when IDs contain colons or match internal specialists. The webhook help dialog documents `/api/integrations/events`; incoming external activity does not change internal run records.

The native modal dialogs trap focus and support Escape. Every canvas character and event bubble has a keyboard-operable button; selecting either opens that agent in the inspector, and the bubble's full text is available to assistive technology and on hover. Bubbles avoid each other, agent centers, and pager controls, with connectors showing their desk association. Sparse desktop maps fill the available office space; crowded or narrow maps grow inside a scrollable office region to keep events readable and reachable. The list view exposes all statuses as text. Reduced-motion preferences disable continuous canvas animation. On narrow screens the inspector appears below the office, and the strategic pyramid is available through an expandable panel.

Workspace settings include a separate **Call budgets** form below model selection: **Model calls per mission**, **Agent model turns per invocation**, and **Tool calls per mission**. The mission model budget covers all generative requests, including reviews and retries; the per-agent limit caps model turns within an invocation. Tool calls have an independent mission-wide cap shared by every agent, including dynamic specialists and Tools R&D. Each field has an independent **No limit** checkbox that disables its number input and saves an explicit JSON `null`. Toggling it off restores the finite draft, or the 100/12/200 defaults after loading saved unlimited settings. Removing a model cap leaves a finite tool cap intact, and removing a tool cap leaves finite model caps intact. Timeouts and revision limits remain in effect. Older two-field settings responses use the existing 200-tool default.

Workspace defaults apply to new missions and remain independent of per-agent model overrides. Budget and model saves preserve unsaved edits in the other form. A selected mission shows its recorded limits and model/tool usage. For paused, review, or failed missions, the separate **Apply saved budgets to this mission** action sends the three saved workspace values to `PUT /api/runs/{id}/budgets`. It stays disabled while the budget form has unsaved changes, and does not change another mission, resume execution, clear review, or reset counters. The server also checks that no worker owns execution; a conflict remains visible and can be retried after execution stops. Regenesis restores all three finite defaults: 100 mission model requests, 12 agent turns, and 200 mission tool calls.

The runtime note also reports the server's web-search provider (Exa or Z.AI MCP) and missing configuration. This is read-only, with no credential or provider-selection form. Older API responses without `web_search` show “Not reported.” Set `EXA_API_KEY` on the server to select Exa automatically for Research and Tools R&D search and contents, or use `WEB_SEARCH_PROVIDER` for an explicit override; `EXA_TIMEOUT` defaults to 30 seconds. Exa failures do not trigger a provider fallback. Existing evidence remains stored, and Engineering's direct URL reader is unchanged.

An unavailable individual Exa page is a recoverable tool result, allowing the agent to try another source or use saved evidence. It does not open a review automatically. Provider credentials, quota, service, or response-schema failures remain blockers; their recorded reason and evidence appear through the normal review flow. No page failure triggers URL rewriting or a direct HTTP fallback.

Human reviews start with a brief explanation and plain next-step choices. The primary button names the selected action. Ordinary retries use the current requirements and recorded feedback, with optional additional instructions; policy and clarification reviews require written guidance. Requirements are editable only after selecting that choice. Evidence, gate feedback, attempts, and files remain under a collapsed disclosure. The UI honors the backend's `allowed_actions` and preserves the exact interrupt ID. Legacy reviews use available recorded context; pending dependencies remain separate from failures.

Files are grouped as task outputs, sources, verification logs, submission metadata, and other files. Source retrievals and metadata records do not count as produced task outputs. Historical zero-byte diagnostic logs remain downloadable and are explicitly labeled as empty logs.
