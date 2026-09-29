# ADR-0010: API conventions

- **Status:** Accepted
- **Date:** 2026-09-29
- **Sub-project:** SP-01b

## Context

Every later sub-project adds endpoints to one API that three clients use: the recruitment web app, the candidate portal and the desktop app (through its Rust client). Master plan §13 fixes the rules: the `/api/v1` prefix, RFC 9457 errors, cursor pagination, `Idempotency-Key` on creates, and a generated client that CI keeps current. §9 adds rate limits per IP, account and organisation; §3.2 asks for server-synchronised event clocks; §11 asks for OpenTelemetry with PII-free logs. Settling these before the first business endpoint means no endpoint invents its own.

## Decision

- **Service.**
  - `backend/api` is a FastAPI app built by `create_app()`.
  - It connects to PostgreSQL as `hirevion_app` (ADR-0009) and to Valkey.
  - Locally it runs natively (`hv api`) behind Caddy. CI builds and starts its image (non-root, digest-pinned).
  - There is no CORS: the web app calls `/api` on its own host, and the desktop calls from Rust.
- **Errors: RFC 9457 problems, always.**
  - `type` is `urn:hirevion:problem:<code>`. That's a stable identifier, not a web page, so it doesn't depend on a domain we don't own yet.
  - `code` repeats the slug for clients that switch on it, and `trace_id` points at the trace.
  - Validation errors list `errors[]` entries with `pointer` (JSON Pointer into the body), `parameter` or `header`.
  - Unhandled exceptions become a generic 500, logged once with the traceback. The body never carries exception text.
  - Middleware errors (host check, body size, rate limits) use the same format.
  - The OpenAPI document declares `4XX`/`5XX` problem responses on every operation.
- **Pagination: keyset with opaque cursors.**
  - Requests take `?limit=` (1–100, default 25) and `&cursor=`; responses are `{items, next_cursor}`.
  - A cursor is URL-safe base64 of `{"v":1,"o":<ordering>,"k":[typed sort keys]}`. One made for another ordering, or tampered with, is 400 `invalid-cursor`.
  - Sort columns are NOT NULL and end with `id`.
  - Tampering can't cross tenants, because row-level security still filters every page.
- **Idempotency: the key lives in the create's own transaction.**
  - `Idempotency-Key` (8–255 characters; the draft's quoted form is accepted too) is required on create endpoints; without it the request is 400.
  - `claim()` inserts the key before the create runs, and the response is stored in the same transaction. So:
    - a retry after commit replays the stored response with `Idempotent-Replayed: true`;
    - a concurrent retry waits for the first (409 after 5 s);
    - a failed create leaves no key.
  - The same key with a different method, path or body is 422 `idempotency-key-reused`.
  - Keys are tenant-scoped rows, purged after 24 hours.
- **Rate limits: GCRA on Valkey.**
  - One Lua script keeps each bucket's theoretical arrival time and uses Valkey's clock, so every API process shares one exact limit.
  - A global per-client-IP rule (600/minute by default) covers every route except health probes. `rate_limited(rule, key)` adds per-route rules; SP-02 adds account and organisation keys.
  - Responses carry `RateLimit-Policy` and `RateLimit` (draft-ietf-httpapi-ratelimit-headers), one list item per rule. A refusal is 429 `rate-limited` with `Retry-After`.
  - If Valkey doesn't answer within 250 ms, a rule is skipped with a warning, or refused with 503 when it is marked `fail_closed` (login and similar).
  - `X-Forwarded-For` counts only from `HV_API_TRUSTED_PROXIES`.
- **Clock sync.**
  - `GET /api/v1/time` returns the server's receive and send times.
  - Clients estimate their offset NTP-style, `((t1 − t0) + (t2 − t3)) / 2`, from the sample with the shortest round trip (`syncClock` in `@hirevion/api-client`).
- **Telemetry.**
  - `setup_telemetry()` exports traces, metrics and logs over OTLP/HTTP to otel-lgtm.
  - It is off unless `OTEL_SDK_DISABLED=false`, so a stack without the obs profile logs no export errors.
  - Requests and queries are traced; health probes are not, including their database and Valkey calls.
  - SQL parameter values and Valkey arguments never reach span attributes.
  - Logs are JSON lines with trace and span ids. A redacting filter masks emails, phone, Aadhaar and PAN numbers, bearer tokens and JWTs, password or secret values, and URL credentials in messages and tracebacks.
  - OpenTelemetry stays on 1.44 because `livekit-agents` 1.8.3 requires `< 1.45`.
- **Contract.**
  - Operation ids are the route functions' names.
  - `hv openapi` writes `packages/api-client/openapi.json` (sorted keys).
  - `@hirevion/api-codegen` runs `openapi-typescript` into `schema.d.ts`. It needs the TypeScript 5 compiler API, which TypeScript 7 no longer ships, so that one tool package pins TypeScript 5.9 while every other package stays on 7.
  - `@hirevion/api-client` wraps `openapi-fetch` and throws non-2xx responses as `ApiProblem`.
  - CI's `api-contract` job fails when either generated file is stale.

## Consequences

- **A new endpoint's checklist.**
  - Put it on `api_router()`.
  - Raise `ProblemError` with a documented code (add it to `docs/api/conventions.md`).
  - List endpoints use `Page` and `paginate()`.
  - Creates take `Depends(idempotency)` and wrap their work in `Idempotency.run()`.
  - Regenerate the contract.
- **Idempotency.** A create's `scope` must identify the caller, so SP-02's principal feeds it. Until then only test routes use it. The purge of expired keys needs a scheduled job (worker SP).
- **Rate-limit keys are personal data.** They hold IPs, but only in Valkey buckets that expire within one rule period.
- **Traces carry route templates, not resource ids,** as span names. URLs with ids appear only as attributes, and must never contain personal data (no emails in paths or query strings).
- **Cloud Migration Plan.**
  - Set `HV_API_TRUSTED_PROXIES` to the ingress range, `HV_API_ALLOWED_HOSTS` to the real hosts, and `OTEL_EXPORTER_OTLP_ENDPOINT` to the collector.
  - Consider `HV_API_DOCS_ENABLED=false` for the public host.
- **Upgrades.** When `livekit-agents` allows OpenTelemetry ≥ 1.45, raise the pin in one change. When `openapi-typescript` supports TypeScript 7, drop the 5.9 isolation.
