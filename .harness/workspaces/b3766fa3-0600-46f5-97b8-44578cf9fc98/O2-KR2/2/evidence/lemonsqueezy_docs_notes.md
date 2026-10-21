================================================================================
Lemon Squeezy API documentation notes — O2-KR2 WP2 fallback retest
Generated (UTC): 2026-10-21T02:32:06Z
Purpose: identify every OFFICIALLY DOCUMENTED Lemon Squeezy API resource that can
create a product or a checkout, and its exact auth requirements, BEFORE any HTTP
attempt. Sources fetched via read_web_page this session; artifact IDs below are
the stored fetch receipts (HTTP 200 unless stated otherwise).
================================================================================

S1. API overview — https://docs.lemonsqueezy.com/api
    (HTTP 200; artifact 98a5ff6b33ad6663e348633770474a8d)
  - REST API, JSON:API 1.0, base URL https://api.lemonsqueezy.com/v1.
  - Authentication: Bearer token — requests carry header
    'Authorization: Bearer {api_key}'; documented rate limit 300 req/min.
  - Products section of the reference navigation, verbatim: "The product
    object", "Retrieve a product", "List all products". There is NO
    "Create a product" entry anywhere in the reference; product creation is a
    dashboard action, not an API resource.

S2. Products list endpoint —
    https://docs.lemonsqueezy.com/api/products/list-all-products
    (HTTP 200; artifact 7d7cea31c795514de3406bf951d79fbf)
  - Verbatim: "GET /v1/products" — List all products.
  - Headers: 'Accept: application/vnd.api+json',
    'Authorization: Bearer {api_key}'.

S3. The checkout object —
    https://docs.lemonsqueezy.com/api/checkouts/the-checkout-object
    (HTTP 200; artifact 7a50aa437ec3ce77d454911b75df779e)
  - Checkouts ARE creatable: the Checkouts nav lists "The checkout object",
    "Create a checkout", "Retrieve a checkout", "List all checkouts".
  - Creation requires relationships to an EXISTING store and an EXISTING
    variant (store_id + variant_id).
  - Response attributes include 'url' (unique, signed), 'test_mode',
    'expires_at' (ISO 8601; null = perpetual), and preview totals such as
    'total_formatted' (docs example "$50.00").
  - Public URL form shown on the page:
    https://my-store.lemonsqueezy.com/checkout/custom/<id>?signature=<64-hex>
    (documentation example content only — NOT a credential, NOT a live offer).
  - Example checkout id on the page: ac470bd4-7c41-474d-b6cd-0f296f5be02a.

S4. Create a checkout —
    https://docs.lemonsqueezy.com/api/checkouts/create-checkout
    (HTTP 200; artifact 735805e85f3b6a0355031b68cefdf9a4)
  - Verbatim heading: "POST /v1/checkouts — Creates a unique checkout for a
    specific variant with specified attributes."
  - Exact auth/headers from the page's own curl example:
      -X "POST" "https://api.lemonsqueezy.com/v1/checkouts"
      -H 'Accept: application/vnd.api+json'
      -H 'Content-Type: application/vnd.api+json'
      -H 'Authorization: Bearer {api_key}'
  - Body: JSON:API "data" with "type": "checkouts"; attributes (custom_price in
    cents, product_options, checkout_options, checkout_data, preview, test_mode,
    expires_at) and relationships store.data.id + variant.data.id (existing
    store/variant required).
  - Success response contains data.attributes.url, e.g.
    "https://my-store.lemonsqueezy.com/checkout/custom/5e8b546c-...?expires=...&signature=<64-hex>"
    and preview.total_formatted for the charged total.
  - Slug note: this page lives at /api/checkouts/create-checkout; the earlier
    URL https://docs.lemonsqueezy.com/api/checkouts/create-a-checkout returned
    HTTP 404 this session (see S5).

S5. URLs that returned HTTP 404 this session (do not retry):
    - https://docs.lemonsqueezy.com/api/requests
    - https://docs.lemonsqueezy.com/api/checkouts/create-a-checkout

S6. Fragment/full-page reconciliation: an earlier partial (tail) capture of the
    checkout-object page started mid-attribute-list; the full-page fetch
    (artifact 7a50aa437ec3ce77d454911b75df779e, S3 above) supersedes it and
    confirms every attribute/relationship fact restated here. No fact in this
    document is relied on from the fragment alone.

S7. Consequences for the O2-KR2 fallback chain:
  1) Product creation via REST: NOT DOCUMENTED AT ALL. The run-1 attempt
     POST https://api.lemonsqueezy.com/v1/products -> 405 "POST method is not
     supported" (evidence/BLOCKER_EVIDENCE.md, 2026-10-20T22:28:52Z) used the
     wrong resource; per official docs there is no product-creation API — it is
     dashboard-only.
  2) The documented-correct creation resource is POST /v1/checkouts (S4), and
     it ALWAYS requires 'Authorization: Bearer {api_key}' plus an existing
     store id and variant id. This is a different, documented-correct resource
     than the failed POST /v1/products.
  3) evidence/lemonsqueezy_credentials_sweep.log (sweep start UTC_NOW=
     2026-10-21T02:04:17Z; sha256 03ae852c1258d63c16ac55c448621ee6679aebe5205bfcdbdc806e1969ccb7e3)
     shows ZERO Lemon Squeezy credentials anywhere on this machine (env incl.
     LS_COLORS, ~/.netrc absent, ~/.config, ~/.env*, git config). Without an
     api_key the documented POST /v1/checkouts cannot be authenticated; the
     fallback attempt in evidence/lemonsqueezy_fallback_retry.log is therefore
     executed UNAUTHENTICATED to capture the canonical auth error verbatim.
  4) KR rule if any call DID return a checkout/product URL: curl the URL and
     require HTTP 200 with the $15 price visible (grep '15') before recording
     it in mission_log.md. Otherwise the retry log must end with the explicit
     conclusion line 'Lemon Squeezy REST fallback blocked (evidence: ...)'.
================================================================================
