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

`GET /api/office` provides a projection and numeric event cursor. The client consumes named `activity` SSE messages from `/api/events?after=<cursor>`, deduplicates sequences, and reconnects from its last applied cursor. A connected status reflects the stream connection; office activity always reflects server events. Idle agents are the initial state, with no simulated work.

The ten internal roles have stable desk positions. External agents are keyed by `source:agent_id`, preserving internal identities even when their raw IDs match. The webhook help dialog documents `/api/integrations/events`; incoming external activity does not change internal run records. Up to six external agents fit the displayed integration row, with additional external agents available through the searchable list view.

The native modal dialogs trap focus and support Escape. Every canvas character has a keyboard-operable button; the list view exposes all statuses as text. Reduced-motion preferences disable continuous canvas animation. On narrow screens the inspector appears below the office, and the strategic pyramid is available through an expandable panel.
