# O2-KR2 blocker register — publish-channel attempts

Register of every blocked publish attempt for offer **pydevtoolkit 1.0.0 @ $15.00**.
All timestamps UTC (`date -u +%Y-%m-%dT%H:%M:%SZ`). Every status line below is copied
verbatim from the referenced log file; no response content is paraphrased.

Outcome summary: **no live offer URL could be created without a human account holder**
→ prepared-asset mode staged; the paste-checkout-link hand-off document is `store/OFFER.md`.

---

## BLOCKER 1 — Gumroad API: 401 Unauthorized (no access token)

* **UTC timestamp:** 2026-10-20T22:12:53Z (attempt start) / 2026-10-20T22:12:54Z (finished)
* **Request:** `POST https://api.gumroad.com/v2/products` (name=pydevtoolkit 1.0.0 — 16 CLI
  developer utilities, price=1500, description from README lines 1–120)
* **Credential probe (2026-10-20T22:05:49Z):** `env | grep -iE 'gumroad|access_token'`
  matched nothing — no `GUMROAD_ACCESS_TOKEN` in the execution environment; request sent
  with empty `access_token` as specified by the playbook command.
* **Exact HTTP status line:** `HTTP_STATUS:401`  (curl exit 0)
* **Raw response:** 0 bytes (empty body). Body file sha256 (empty string):
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
  `BODY_BYTES: 0` — publish tool rejects empty files, so the body file exists on disk but
  has no publishable text artifact.
* **Log path:** `evidence/publish/gumroad_attempt.log`
  (published artifact `0b1bb54fb26787dee2a0bc42d710666e`)
* **Interpretation:** Gumroad requires a valid account access token to create products.
  Token creation is a human dashboard step (account → Settings → Advanced → Application
  page). This is the sanctioned "blocked" outcome; the dashboard listing procedure is
  documented in `store/OFFER.md` Step A and `store/gumroad_listing.md`.

---

## BLOCKER 2 — Lemon Squeezy REST API: 405 Method Not Allowed (POST not supported)

* **UTC timestamp:** 2026-10-20T22:13:33Z (attempt start) / 2026-10-20T22:13:34Z (finished)
* **Request:** `POST https://api.lemonsqueezy.com/v1/products` with headers
  `Authorization: Bearer ${LEMON_SQUEEZY_API_KEY:-}`,
  `Accept: application/vnd.api+json`, `Content-Type: application/vnd.api+json`,
  body `evidence/publish/lemonsqueezy_payload.json`
  (JSON:API `type: products`, name/description/`price: 1500`/`status: published`)
* **Credential probe (2026-10-20T22:05:49Z):** `env | grep -iE 'lemon|squeezy'`
  matched nothing — no `LEMON_SQUEEZY_API_KEY` in the execution environment; Bearer sent
  empty as specified by the assignment.
* **Exact HTTP status line:** `HTTP_STATUS:405`  (curl exit 0)
* **Raw response — first lines of `evidence/publish/lemonsqueezy_body.txt` (184 B):**

  ```json
  {"jsonapi":{"version":"1.0"},"errors":[{"detail":"The POST method is not supported for route v1\/products. Supported methods: GET, HEAD.","status":"405","title":"Method Not Allowed"}]}
  ```

* **Log path:** `evidence/publish/lemonsqueezy_attempt.log`
  (published artifact `e666302f67d9b4494e2fee9078632e5a`; body artifact `7e0e197f69c481fd072acb819b919f9c`)
* **Corroboration:** `https://docs.lemonsqueezy.com/api/products` (fetched 2026-10-20 UTC,
  artifact `d487e23812901d61506b8dc8a3e0671f`) documents only *Retrieve a product* and
  *List all products* — the REST API has no create-product endpoint; products are created
  in the dashboard. Independent of the missing API key.
* **Interpretation:** Lemon Squeezy product creation cannot be automated via REST. The
  dashboard procedure is documented in `store/OFFER.md` Step B.

---

## Not blockers / context

* **Environment sanity:** DNS/TLS and HTTP reachability to `api.gumroad.com` verified by a
  real probe at 2026-10-20T22:05:49Z (`HTTP_STATUS:401` on an unauthenticated GET-shaped
  probe) — network was never the blocker; the endpoints answered normally.
* **Sanctioned fallback:** per assignment, prepared-asset mode (single hand-off document
  `store/OFFER.md` + empty `store/CHECKOUT_LINK.txt` placeholder) is the correct terminal
  state when both channels are blocked; no `escalate_blocker` call is warranted for these
  normal blocked-API outcomes.
* **Known non-viable channels** (researched upstream, not attempted here): Fiverr — no
  seller API and phone verification required before gig creation (artifact
  `15450fbe905c3958026293256c5a7e60`); Upwork — API gated at $25k lifetime earnings +
  JSS ≥ 90% (artifact `e79e4fcca0536e071dad9a58498ceea0`).
