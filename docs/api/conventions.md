# Hirevion API conventions for client developers

How the Hirevion API behaves, for anyone calling it: the web app, the candidate portal, the desktop app's Rust client, and third-eye. [ADR-0010](../architecture/adr/0010-api-conventions.md) records why.

## Basics

- Every route is under `/api/v1`, and every JSON body is UTF-8.
- The web app calls `/api/...` on its own host. The API allows no cross-origin browser calls.
- The contract is `packages/api-client/openapi.json`, published at `/api/v1/openapi.json` with interactive docs at `/api/v1/docs`.
- TypeScript clients use `@hirevion/api-client`:

  ```ts
  import { createApiClient, isApiProblem, newIdempotencyKey } from "@hirevion/api-client";

  const api = createApiClient({ baseUrl: window.location.origin });
  const { data } = await api.GET("/api/v1/health/live"); // typed from the OpenAPI document
  ```

## Errors

Every error is an RFC 9457 problem with media type `application/problem+json`:

```json
{
  "type": "urn:hirevion:problem:validation-failed",
  "title": "Validation failed",
  "status": 422,
  "detail": "The request doesn't match the schema; see `errors`.",
  "instance": "/api/v1/jobs",
  "code": "validation-failed",
  "trace_id": "0af7651916cd43dd8448eb211c80319c",
  "errors": [{ "pointer": "#/title", "detail": "Field required" }]
}
```

- **Switch on `code`.** `title` and `detail` are for people and may change.
- **`errors[]` entries** name what failed:
  - `pointer`: a JSON Pointer into the request body;
  - `parameter`: a path or query parameter;
  - `header`: a request header.
- **Show `trace_id`** in error screens and support requests. It finds the request in the traces.
- **`@hirevion/api-client` throws `ApiProblem`** for every non-2xx response, including a proxy's 502 without a problem body (`code: "bad-gateway"`).

| Code | Status | Meaning | What the client does |
|---|---|---|---|
| `bad-request` | 400 | Generic client error | Fix the request |
| `host-not-allowed` | 400 | Wrong `Host` | Call the right host |
| `invalid-cursor` | 400 | The cursor doesn't belong to this list | Restart the list without a cursor |
| `idempotency-key-missing` | 400 | A create without `Idempotency-Key` | Send one |
| `idempotency-key-invalid` | 400 | Key not 8–255 of `A-Z a-z 0-9 _ . : -` | Use `newIdempotencyKey()` |
| `not-found` | 404 | No such route or resource (or not yours) | — |
| `method-not-allowed` | 405 | Wrong method; see `Allow` | — |
| `idempotency-request-in-progress` | 409 | The same key is still being processed | Retry after `Retry-After` |
| `payload-too-large` | 413 | Body over the limit (1 MiB by default) | Upload files through storage URLs instead |
| `validation-failed` | 422 | Body, parameter or header invalid; see `errors[]` | Show field errors |
| `idempotency-key-reused` | 422 | The key was used for a different request | New operation, new key |
| `rate-limited` | 429 | Too many requests | Wait `Retry-After` seconds |
| `internal-error` | 500 | Our bug | Show `trace_id`; retry creates with the same key |
| `service-unavailable` | 503 | A dependency is down | Retry with backoff |

## Lists

- **Request:** `GET /api/v1/<things>?limit=25&cursor=<next_cursor>`, where `limit` is 1–100.
- **Response:** `{"items": [...], "next_cursor": "..."}`. `next_cursor` is `null` on the last page.
- **Cursors are opaque.** Pass them back unchanged, and only to the same list with the same sorting.

## Creating things (idempotency)

- **Every create needs an `Idempotency-Key` header.** Make one key per logical operation and reuse it for every retry of that operation:

  ```ts
  const key = newIdempotencyKey();
  // retries of this create send the same key
  await api.POST("/api/v1/jobs", { params: { header: { "Idempotency-Key": key } }, body });
  ```

- **After the first attempt succeeds,** a retry gets the same status and body back, with `Idempotent-Replayed: true`, and nothing is created twice.
- **If the first attempt failed,** the retry runs again.
- **A different body with a used key** is `idempotency-key-reused`.
- **Keys expire after 24 hours.**

## Rate limits

- **Headers:** responses carry `RateLimit-Policy` (for example `"ip";q=600;w=60`) and `RateLimit` (for example `"ip";r=598;t=1`). There is one item per rule that applied, where `r` is the requests left and `t` the seconds until the bucket is full again.
- **When refused:** the response is 429 `rate-limited` with `Retry-After`. Wait that long; don't retry immediately.

## Server time

- **Why:** event times the desktop and third-eye send must be on the server clock.
- **How:** call `syncClock(api)` at startup and every few minutes, then add `offsetMs` to local timestamps. It samples `GET /api/v1/time` and trusts the fastest round trip.
- **The endpoint:** `GET /api/v1/time` returns:
  - `received_at_ms`: when the server received the request;
  - `sent_at_ms`: when it answered.

  Both are Unix milliseconds on the server clock.

## Health

- **`GET /api/v1/health/live`:** the process is up.
- **`GET /api/v1/health/ready`:** PostgreSQL and Valkey answer. When a dependency is down, the response is 503 with `checks`.
- **Neither is rate-limited or traced.**
