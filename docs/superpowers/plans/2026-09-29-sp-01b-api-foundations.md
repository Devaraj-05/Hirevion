# SP-01b API Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `api` service with the conventions every later endpoint inherits: RFC 9457 errors, cursor pagination, `Idempotency-Key` on creates, rate limits, a clock-sync endpoint, OpenTelemetry with redacted logs, and an OpenAPI → TypeScript client that CI keeps in step with the server.

**Architecture:**

- **Service.** A new uv workspace member, `backend/api` (package `hirevion_api`), is a FastAPI app built by `create_app()`. Every route lives under `/api/v1`. It connects to PostgreSQL as `hirevion_app` (SP-01a) and to Valkey. Locally it runs natively with `uv run hv api` on `127.0.0.1:8000`, where Caddy already routes `app.hirevion.localhost/api/*` and `api.hirevion.localhost`.
- **Shared pieces go in `hirevion_core`**, because the realtime service and workers need them too: the idempotency store, the rate limiter, telemetry setup and log redaction. HTTP specifics (headers, status codes, dependencies, middleware) stay in `hirevion_api`.
- **No endpoints for business data yet.** SP-02 onwards add them. The conventions here are tested through routers that exist only in the tests; the real routes are health, clock sync and the OpenAPI document.
- **Contract.**
  - `hv openapi` writes `packages/api-client/openapi.json`.
  - A small tool package runs `openapi-typescript` to generate `packages/api-client/src/schema.d.ts`.
  - `@hirevion/api-client` wraps `openapi-fetch`.
  - CI fails when either generated file is stale.

**Tech Stack:**

- Python: FastAPI 0.141, uvicorn 0.54, SQLAlchemy 2 async + asyncpg, redis-py (asyncio) on Valkey 8.
- OpenTelemetry SDK 1.45 with OTLP/HTTP exporters, plus the FastAPI, SQLAlchemy and Redis instrumentations (0.66b0).
- TypeScript: `openapi-typescript` 7.13 (needs TypeScript 5.9.3, isolated in `tools/api-codegen`), `openapi-fetch` 0.17, Vitest.

## Global Constraints

- Everything in `MASTER_IMPLEMENTATION_PLAN.md` §13 applies:
  - `/api/v1` prefix;
  - RFC 9457 errors;
  - cursor pagination;
  - `Idempotency-Key` on creates;
  - the OpenAPI client is regenerated in CI and drift fails the build;
  - TDD, and ≥ 85 % line coverage on domain modules.
- Same-origin only. The web app reaches the API on its own host (`/api` on `app.`), and the desktop calls it from Rust. There is no CORS middleware, so cross-origin browser calls are refused.
- Every error response is `application/problem+json`. It never contains a stack trace, SQL, a secret or another tenant's data. It carries `trace_id` so support can find the trace.
- Logs and spans never carry passwords, tokens, email addresses, phone numbers, Aadhaar or PAN numbers (master plan §11).
- Rate limiting and idempotency use Valkey and PostgreSQL from `hv up`; tests run against the real services (the `db` marker), never mocks.
- Secrets come only from the root `.env`. Nothing in `packages/api-client` may contain a key.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/api/pyproject.toml` | Package `hirevion-api` |
| `backend/api/src/hirevion_api/settings.py` | `ApiSettings` (`HV_API_*`): hosts, proxies, body limit, rate limits, docs switch |
| `backend/api/src/hirevion_api/app.py` | `create_app()`: middleware, handlers, routers, lifespan (database, Valkey, telemetry) |
| `backend/api/src/hirevion_api/main.py` | `app = create_app()` for uvicorn |
| `backend/api/src/hirevion_api/problems.py` | `Problem`, `ProblemError`, exception handlers, OpenAPI error responses |
| `backend/api/src/hirevion_api/routing.py` | Operation ids and the `/api/v1` router factory |
| `backend/api/src/hirevion_api/middleware.py` | Host check, body-size limit, security headers (pure ASGI) |
| `backend/api/src/hirevion_api/deps.py` | `get_db`, `get_redis`, `client_ip` |
| `backend/api/src/hirevion_api/health.py` | `GET /health/live`, `GET /health/ready` |
| `backend/api/src/hirevion_api/pagination.py` | `PageParams`, `Page[T]`, cursor encoding, `paginate()` |
| `backend/api/src/hirevion_api/idempotency.py` | The `Idempotency-Key` dependency and response replay |
| `backend/api/src/hirevion_api/ratelimit.py` | Global per-IP middleware, `rate_limited()` dependency, RateLimit headers |
| `backend/api/src/hirevion_api/clock.py` | `GET /time` |
| `backend/api/src/hirevion_api/openapi.py` | Stable OpenAPI export |
| `backend/api/Dockerfile` | Production image (multi-stage, non-root, digest-pinned) |
| `backend/core/src/hirevion_core/idempotency.py` | `claim()` / `remember()` / `purge_idempotency_keys()` over `idempotency_keys` |
| `backend/core/src/hirevion_core/ratelimit.py` | `RateRule`, `RateDecision`, `RateLimiter` (GCRA in a Valkey script) |
| `backend/core/src/hirevion_core/telemetry.py` | `setup_telemetry()`: traces, metrics, logs over OTLP |
| `backend/core/src/hirevion_core/logging.py` | `configure_logging()`, JSON formatter, `redact()` |
| `backend/migrations/versions/0004_idempotency_keys.py` | The idempotency table |
| `packages/api-client/{openapi.json,src/schema.d.ts,src/client.ts,src/problem.ts,src/clock.ts,src/index.ts}` | The TypeScript client |
| `tools/api-codegen/package.json` | `openapi-typescript` with its own TypeScript 5.9.3 |
| `tools/devcli/src/hirevion_devcli/cli.py` | `hv api`, `hv openapi [--check]` |
| `.github/workflows/ci.yml` | The `api-contract` job and the API image build |
| `docs/architecture/adr/0010-api-conventions.md`, `docs/api/conventions.md` | Decisions and the client developer's reference |

---

### Task 1: The API service, problem details and health checks

**Interfaces:**

- Consumes:
  - `CoreSettings`, `load_core_settings()`;
  - `Database`, `create_database(settings, "app")` (SP-01a).
- Produces:
  - `create_app(api: ApiSettings | None = None, *, core: CoreSettings | None = None, db: Database | None = None, redis: Redis | None = None, telemetry: bool = False) -> FastAPI`. Injected `db`/`redis` are used as-is and never disposed. Otherwise the lifespan creates them from `core` (loaded lazily, so building the app needs no `.env`).
  - `ProblemError(status: int, code: str, title: str, detail: str | None = None, **extensions)` → an `application/problem+json` response.
  - `problem_type(code) -> str` = `"urn:hirevion:problem:" + code`.
  - `api_router(**kwargs) -> APIRouter` with prefix `/api/v1`, and the 4XX/5XX problem responses documented.
  - `get_db(request) -> Database`, `get_redis(request) -> Redis`, `client_ip(request) -> str`.
  - `hv api [--port 8000] [--reload/--no-reload]`.

- [ ] Add the workspace member `backend/api`:
  - dependencies `hirevion-core`, `fastapi>=0.141`, `uvicorn>=0.54`;
  - root `pyproject.toml`: add it to the members, sources, root dependencies, `known-first-party` and `testpaths`;
  - `hv api` runs `python -m uvicorn hirevion_api.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend --no-access-log`.
- [ ] Tests first (`backend/api/tests/`). The fixture `make_app(**overrides)` builds `create_app()` with a test router mounted. It uses `httpx.AsyncClient(transport=ASGITransport(app, raise_app_exceptions=False), base_url="http://api.hirevion.localhost")`.
  - **Problems:**
    - a route raising `ProblemError(409, "conflict-example", "Conflict", detail="x", thing=1)` gives status 409, `content-type: application/problem+json`, and a body with `type` `urn:hirevion:problem:conflict-example`, `title`, `status`, `detail`, `instance` (the request path), `code`, `thing` and `trace_id` (a key present even with telemetry off: `null`).
  - **Validation:**
    - a bad JSON body field gives 422 `validation-failed` with `errors: [{"pointer": "#/email", "detail": …}]`;
    - a bad query parameter gives `{"parameter": "limit", …}`;
    - a bad header gives `{"header": "…", …}`.
  - **Routing errors:**
    - an unknown path gives 404 `not-found`;
    - a wrong method gives 405 `method-not-allowed` with an `Allow` header.
  - **Unhandled errors:**
    - an exception in a route gives 500 `internal-error`. The body contains neither the exception text nor its type. The error is logged with its traceback.
  - **Middleware:**
    - `Host: evil.example` gives 400 `host-not-allowed`;
    - a body over `max_body_bytes`, declared or streamed, gives 413 `payload-too-large`;
    - every response carries `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`;
    - `X-Forwarded-For: 203.0.113.9` from a trusted proxy (the test client is `127.0.0.1`) makes `client_ip()` return `203.0.113.9`, and with `trusted_proxies="10.0.0.1"` it is ignored.
  - **Health:**
    - `GET /api/v1/health/live` gives 200 `{"status": "ok"}` with no dependencies.
    - `db`-marked:
      - `GET /api/v1/health/ready` gives 200 `{"status": "ok", "checks": {"database": "ok", "valkey": "ok"}}`;
      - with a Valkey client pointing at port 1, it gives 503 `service-unavailable` with `checks.valkey == "unavailable"`.
  - **Lifespan:** `async with app.router.lifespan_context(app)` creates and disposes its own `Database` and Valkey client from `core` (`db`-marked).
  - **OpenAPI:** operation ids are the route function names (`get_liveness`, `get_readiness`), and every operation lists the `4XX`/`5XX` problem responses.
  - **CLI:** `hv api` runs the command above (test via the `calls` fixture in `test_cli_stack.py`).
- [ ] Implement `problems.py`:

```python
PROBLEM_MEDIA_TYPE = "application/problem+json"


class Problem(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    code: str
    trace_id: str | None = None


class ProblemError(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str | None = None,
                 headers: Mapping[str, str] | None = None, **extensions: Any) -> None: ...
```

  - Handlers:
    - `ProblemError`;
    - `RequestValidationError`. Map `loc` to a pointer: `("body", "a", 0)` → `"#/a/0"`; `("query", n)` → `parameter`; `("header", n)` → `header`; `("path", n)` → `parameter`.
    - `StarletteHTTPException` (404/405 keep their headers);
    - `Exception`: 500, `log.exception`, generic detail.
  - `trace_id` is the current span's trace id as 32 hex characters, or `None` when no span is recording.
- [ ] Implement `middleware.py`, three pure ASGI classes that write problem responses themselves:
  - `HostCheckMiddleware(allowed_hosts)`: exact match on the host without its port;
  - `BodySizeLimitMiddleware(max_bytes)`: checks `content-length`, then counts streamed `http.request` chunks;
  - `SecurityHeadersMiddleware`: adds the two headers unless a route set them.
- [ ] Proxy headers: wrap the app in `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware(trusted_hosts=api.trusted_proxies)`, so it behaves the same under `hv api`, tests and the container.
- [ ] Implement `settings.py`:

```python
class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HV_API_", extra="ignore")
    allowed_hosts: str = "api.hirevion.localhost,app.hirevion.localhost,localhost,127.0.0.1"
    trusted_proxies: str = "127.0.0.1"
    max_body_bytes: int = 1_048_576
    ip_rate_limit: int = 600           # requests per window per client IP (Task 4)
    ip_rate_window_seconds: int = 60
    docs_enabled: bool = True
```

  Also `routing.py`: `generate_unique_id_function=lambda route: route.name`. And `health.py`: readiness runs `SELECT 1` through `db.unscoped()` and `redis.ping()`, each under `asyncio.timeout(2)`.
- [ ] Commit `feat(api): add the API service with problem details and health checks`.

### Task 2: Cursor pagination

**Interfaces:**

- Produces:
  - `PageParams(limit: int, cursor: str | None)` and the dependency `page_params(limit: Query(1..100) = 25, cursor: Query(max_length=1024) = None)`.
  - `Page[T]` (Pydantic generic): `items: list[T]`, `next_cursor: str | None`.
  - `encode_cursor(order: str, values: Sequence[CursorValue]) -> str` and `decode_cursor(order: str, cursor: str) -> list[CursorValue]`. They raise `ProblemError(400, "invalid-cursor", …)`. `CursorValue = UUID | datetime | date | int | str | Decimal | None`.
  - `paginate(session, stmt, order_by: Sequence[InstrumentedAttribute[Any]], params, *, descending=False) -> tuple[list[Any], str | None]`. `order_by` must end with a unique column (normally `id`).

- [ ] Tests first:
  - Pure tests:
    - encode then decode returns the same `UUID`, aware `datetime`, `Decimal`, `int`, `str` and `None` values;
    - a cursor is URL-safe base64 with no padding;
    - a cursor made for order `"created_at,id:asc"` is rejected with `invalid-cursor` for `"id:asc"`;
    - garbage, a wrong version or the wrong value count is rejected with `invalid-cursor`.
  - DB tests, using an admin `AsyncSession` over 7 organisations with a unique name prefix:
    - pages of 3 by `id` ascending give 3, 3, 1 rows, with no duplicates and none missing;
    - the last page's `next_cursor` is `None`;
    - descending pages come back in reverse;
    - ordering by `(created_at, id)` works across equal `created_at` values (insert them in one transaction, so `now()` is equal).
  - API test (test router returning `Page[OrgOut]`):
    - `limit=0` gives 422 with `parameter: "limit"`;
    - a tampered cursor gives 400 `invalid-cursor`.
- [ ] Implement:
  - **Cursor format:** `base64url(json({"v": 1, "o": order, "k": [tagged values]}))` without padding. Tagged values are `{"u": "…"}` (UUID), `{"t": "…"}` (datetime ISO), `{"d": "…"}` (date), `{"n": "…"}` (Decimal), and plain JSON for `int`/`str`/`None`.
  - **Order signature:** `order` is `",".join(column.key for column in order_by) + (":desc" if descending else ":asc")`.
  - **Query:** `paginate` adds `tuple_(*order_by) > tuple_(*values)` (or `<` when descending), orders by the columns in the same direction, fetches `limit + 1` rows, and builds `next_cursor` from the last returned row when there was an extra row.
- [ ] Commit `feat(api): add cursor pagination`.

### Task 3: Idempotency keys on creates

**Interfaces:**

- Produces (core):
  - `claim(session, organization_id, scope, key, fingerprint) -> StoredResponse | None`:
    - `None` means go ahead, then call `remember()`;
    - `StoredResponse(status_code, body)` means replay.
    - It raises `IdempotencyKeyReused` (same key, different request) or `IdempotencyInProgress` (another transaction still holds it after the 5 s lock timeout).
  - `remember(session, organization_id, scope, key, status_code, body) -> None`.
  - `purge_idempotency_keys(conn, older_than: timedelta) -> int`.
- Produces (API):
  - The dependency `idempotency(request, idempotency_key: Header(alias="Idempotency-Key") = None) -> Idempotency`.
  - `Idempotency.run(session, organization_id, scope, create: Callable[[], Awaitable[BaseModel]]) -> BaseModel`.
  - A replay returns the stored status and body with `Idempotent-Replayed: true`.

- [ ] Tests first:
  - DB tests (core):
    - the first `claim` returns `None`;
    - after `remember` and commit, a second `claim` with the same fingerprint returns the stored response;
    - a different fingerprint raises `IdempotencyKeyReused`;
    - a key claimed by an open transaction makes a concurrent `claim` wait. When the first commits, the waiter replays. When the first rolls back, the waiter proceeds (`asyncio.gather` with an `asyncio.Event` between them);
    - tenants can't read each other's keys;
    - `purge_idempotency_keys(conn, timedelta(hours=24))` removes only older rows.
  - API tests, with a test router `POST /api/v1/test/widgets` that inserts an outbox event (SP-01a `publish_event`) so side effects can be counted:
    1. No header gives 400 `idempotency-key-missing`, and a malformed key (`"a b"`, or 300 characters) gives 400 `idempotency-key-invalid`.
    2. The same key and body twice give 201 both times with the same body. The second response carries `Idempotent-Replayed: true`, and only one outbox row exists.
    3. The same key with a different body gives 422 `idempotency-key-reused`.
    4. A handler raising `ProblemError(409, …)` stores nothing, so a retry with the same key runs again.
    5. The key is accepted quoted (the draft's sf-string form `"abc…"`) and bare.
- [ ] Migration `0004_idempotency_keys`:
  - columns: `organization_id uuid` (FK), `scope text`, `key text`, `fingerprint bytea`, `status_code smallint NULL`, `response jsonb NULL`, `created_at timestamptz DEFAULT now()`;
  - PK `(organization_id, scope, key)`; index on `created_at`;
  - tenant RLS;
  - app role `SELECT, INSERT` plus `UPDATE (status_code, response)`.
- [ ] Implement `claim`:
  - `SET LOCAL lock_timeout = '5s'`;
  - `INSERT … ON CONFLICT DO NOTHING RETURNING key`;
  - if nothing was returned, `SELECT fingerprint, status_code, response`;
  - `SET LOCAL lock_timeout TO DEFAULT`;
  - an asyncpg `LockNotAvailableError` becomes `IdempotencyInProgress`.
- [ ] Implement the API side:
  - `fingerprint = sha256(method + "\n" + path + "\n" + body)`;
  - key pattern `[A-Za-z0-9_.:-]{8,255}` after stripping one pair of surrounding quotes;
  - the status code comes from `request.scope["route"].status_code`;
  - the stored body is `result.model_dump(mode="json", by_alias=True)`;
  - a replay raises `IdempotentReplay(stored)`, which an exception handler turns into the `JSONResponse`;
  - core errors become 422 `idempotency-key-reused` and 409 `idempotency-request-in-progress`.
- [ ] Commit `feat(api): add Idempotency-Key handling for creates`.

### Task 4: Rate limits

**Interfaces:**

- Produces (core):
  - `RateRule(name: str, limit: int, period_seconds: int, fail_closed: bool = False)`;
  - `RateDecision(allowed: bool, remaining: int, retry_after_seconds: int, reset_seconds: int)`;
  - `RateLimiter(redis).hit(rule, subject, cost=1) -> RateDecision`, on key `hv:rl:<rule.name>:<subject>`.
- Produces (API):
  - `RateLimitMiddleware(app, limiter_factory, rule)`: the global per-IP limit. It skips `/api/v1/health/*`.
  - `rate_limited(rule, key: Callable[[Request], str] = by_ip)`: a route dependency, for SP-02's login and account limits.
  - `by_ip(request) -> str`.

- [ ] Tests first:
  - DB-marked (real Valkey, database 15):
    - with `RateRule("t", 3, 60)`, three hits are allowed with `remaining` 2, 1, 0, and the fourth is denied with `retry_after_seconds` between 1 and 20;
    - subjects are independent;
    - after the emission interval passes, one more hit is allowed (use `RateRule("t", 2, 1)` and sleep 0.6 s);
    - concurrent hits (`gather` of 20 against limit 10) allow exactly 10.
  - API:
    - with `HV_API_IP_RATE_LIMIT=2`, the third request from one IP gives 429 `rate-limited` with `Retry-After`;
    - responses carry `RateLimit-Policy: "ip";q=2;w=60` and `RateLimit: "ip";r=<remaining>;t=<seconds>`;
    - another `X-Forwarded-For` IP is unaffected;
    - health checks are never limited.
  - Valkey unreachable:
    - the global limit fails open (request served, warning logged);
    - a `fail_closed` route rule gives 503 `service-unavailable`.
- [ ] Implement GCRA in one Lua script run with `EVALSHA`, loaded through redis-py `register_script`. The script uses the server clock, so API instances need no clock agreement:

```lua
local limit, period, cost = tonumber(ARGV[1]), tonumber(ARGV[2]) * 1000, tonumber(ARGV[3])
local now_parts = redis.call('TIME')
local now = now_parts[1] * 1000 + math.floor(now_parts[2] / 1000)
local interval = period / limit
local tat = math.max(tonumber(redis.call('GET', KEYS[1]) or now), now)
local new_tat = tat + interval * cost
if new_tat - period > now then
  return {0, math.floor((period - (tat - now)) / interval), math.ceil(new_tat - period - now), math.ceil(tat - now)}
end
redis.call('SET', KEYS[1], new_tat, 'PX', math.ceil(new_tat - now))
return {1, math.floor((period - (new_tat - now)) / interval), 0, math.ceil(new_tat - now)}
```

  It returns `allowed, remaining, retry_after_ms, reset_ms`. Python rounds the milliseconds up to seconds.
- [ ] Implement the middleware and dependency:
  - the headers follow draft-ietf-httpapi-ratelimit-headers (`RateLimit-Policy`, `RateLimit`, and `Retry-After` on 429);
  - a `RedisError` or `TimeoutError` (with a 250 ms budget) fails open, or gives 503 when `fail_closed`.
- [ ] Commit `feat(api): add GCRA rate limits on Valkey`.

### Task 5: OpenTelemetry and redacted logs

**Interfaces:**

- Produces:
  - `setup_telemetry(service_name: str, *, span_exporter: SpanExporter | None = None, metrics: bool = True, logs: bool = True, set_global: bool = True) -> Telemetry`.
    - `Telemetry` has `tracer_provider`, `meter_provider | None`, `logger_provider | None` and `shutdown()`.
    - The exporter defaults to OTLP/HTTP at `OTEL_EXPORTER_OTLP_ENDPOINT` (default `http://127.0.0.1:4318`).
    - `OTEL_SDK_DISABLED=true` returns no-op providers.
  - `instrument_engine(engine: AsyncEngine, telemetry)`, and `instrument_redis()` with `sanitize_query=True`.
  - `configure_logging(level="INFO", json_output=True)` and `redact(text: str) -> str`.
  - `create_app(..., telemetry=True)` instruments FastAPI with `excluded_urls="api/v1/health/"`.

- [ ] Tests first:
  - Redaction (pure). Each of these is replaced by `[redacted-…]`:
    - emails;
    - Indian and international phone numbers (`+91 98765 43210`, `9876543210`);
    - Aadhaar numbers (`1234 5678 9012`);
    - PAN (`ABCDE1234F`);
    - `Bearer …` tokens and JWTs;
    - `password=…` / `"password": "…"`.
  - Ordinary numbers such as ids, timestamps and UUIDs survive.
  - Logging:
    - the JSON formatter emits `ts`, `level`, `logger`, `message`, `trace_id` and `span_id`, and `exc` when there is a traceback;
    - a log call with an email in its args is redacted after formatting.
  - Telemetry, with an `InMemorySpanExporter` and `set_global=False`:
    - `GET /api/v1/health/live` records no span (excluded);
    - a test route records a server span with `http.route` `/api/v1/test/boom`;
    - that route's 500 problem has `trace_id` equal to the span's trace id;
    - a SQL query inside the request creates a child span without parameter values.
  - With `OTEL_SDK_DISABLED=true`, `setup_telemetry` exports nothing and doesn't fail when no collector is running.
- [ ] Implement:
  - The resource carries `service.name`, `service.version` (package version) and `deployment.environment` (`HV_ENVIRONMENT`, default `development`).
  - Processors: `BatchSpanProcessor`; `PeriodicExportingMetricReader` (60 s); `BatchLogRecordProcessor` with `LoggingHandler` from `opentelemetry.sdk._logs` on the root logger.
  - The redaction filter sits on the handlers, so both stdout and OTLP logs are redacted.
- [ ] The API lifespan calls `setup_telemetry("hirevion-api")` when `telemetry=True` (`main.py` passes it), instruments the engine and Valkey, and `shutdown()`s on exit.
- [ ] Commit `feat(core): add OpenTelemetry setup and redacted structured logs`.

### Task 6: Clock sync, the OpenAPI export and the TypeScript client

**Interfaces:**

- Produces:
  - `GET /api/v1/time` returns `ServerTime(received_at_ms: int, sent_at_ms: int)` with `Cache-Control: no-store`. It is public and subject to the IP limit.
  - `openapi_json(app) -> str`: stable text (`indent=2`, sorted keys, trailing newline).
  - `hv openapi [--check]`: writes, or compares, `packages/api-client/openapi.json`.
  - `@hirevion/api-client` exports:
    - `createApiClient(options: { baseUrl: string; fetch?: typeof fetch }) -> Client<paths>`;
    - `ApiProblem` (extends `Error`; `status`, `code`, `title`, `detail`, `traceId`, `errors`, `raw`) and `isApiProblem`;
    - `newIdempotencyKey()` (a UUID);
    - `estimateClockOffset(samples: ClockSample[]) -> { offsetMs: number; rttMs: number }`;
    - `syncClock(client, rounds = 5, now = () => Date.now())`.

- [ ] Tests first:
  - Python:
    - `GET /api/v1/time` gives `received_at_ms <= sent_at_ms`, within 1 s of the test's `time.time()`, with `no-store`;
    - `openapi_json(create_app())` equals the committed `packages/api-client/openapi.json` (the same check as `hv openapi --check`);
    - `hv openapi --check` exits 1 and names the file when it differs (CLI test with a temporary repository).
  - TypeScript (Vitest):
    - a `problem+json` 404 from a fake `fetch` is thrown as `ApiProblem` with `code` and `traceId`;
    - a plain 502 without a problem body becomes `ApiProblem` with `code: "bad-gateway"`;
    - `estimateClockOffset` picks the lowest-RTT sample. For `t0=1000, t1=1600, t2=1602, t3=1010` it returns `offsetMs 596` (`((1600-1000) + (1602-1010)) / 2`) and `rttMs 8` (`(1010-1000) - (1602-1600)`);
    - `syncClock` calls `/api/v1/time` `rounds` times.
- [ ] Implement `tools/api-codegen`:
  - a pnpm workspace member, devDependencies `openapi-typescript@7.13.0` and `typescript@5.9.3`;
  - script `generate`: `openapi-typescript ../../packages/api-client/openapi.json -o ../../packages/api-client/src/schema.d.ts`.
  - Add `tools/api-codegen` to `pnpm-workspace.yaml`. Biome ignores `packages/api-client/openapi.json` and `packages/api-client/src/schema.d.ts`.
- [ ] Implement `packages/api-client`:
  - dependency `openapi-fetch@0.17.0`;
  - `client.ts` uses `createClient<paths>` with a middleware whose `onResponse` throws `ApiProblem` for any non-2xx.
  - `clock.ts` implements the offset formula:

```ts
export function estimateClockOffset(samples: ClockSample[]): { offsetMs: number; rttMs: number } {
  // NTP: offset = ((t1 - t0) + (t2 - t3)) / 2, rtt = (t3 - t0) - (t2 - t1); trust the fastest round.
}
```

- [ ] CI: a new `api-contract` job (ubuntu) with uv and pnpm:
  - `uv sync --locked`;
  - `uv run hv openapi --check`;
  - `pnpm install --frozen-lockfile`;
  - `pnpm --filter @hirevion/api-codegen generate`;
  - `git diff --exit-code packages/api-client/src/schema.d.ts`.
- [ ] Commit `feat(api): add clock sync and the generated TypeScript client`.

### Task 7: API image, docs and finish

- [ ] `backend/api/Dockerfile`:
  - Stages:
    1. `ghcr.io/astral-sh/uv:<version>-python3.12-bookworm-slim` runs `uv sync --locked --no-dev --package hirevion-api --no-editable` into `/app/.venv`;
    2. `python:3.12-slim-bookworm` copies the venv and `backend/migrations`.
  - Pin both images by digest (look them up with `docker buildx imagetools inspect <image>`).
  - Runtime: user `10001`; `HEALTHCHECK` hits `/api/v1/health/live`; `CMD ["uvicorn", "hirevion_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]`.
  - Add `.dockerignore`.
  - Since `migrate()` finds `backend/migrations` from the package path, copy it to the same relative place, or set `HV_MIGRATIONS_DIR`, which `migrate.py` reads first (add the override and a test).
- [ ] CI:
  - the `compose` job also runs `docker build -f backend/api/Dockerfile .`;
  - it then starts the image with `OTEL_SDK_DISABLED=true` and waits for `/api/v1/health/live` to answer 200.
- [ ] Docs:
  - **ADR-0010 (API conventions):**
    - problem types as URNs and the code catalogue;
    - the cursor format;
    - idempotency semantics and status codes;
    - GCRA and its headers;
    - the clock-sync formula;
    - telemetry and redaction;
    - same-origin (no CORS);
    - the TypeScript 5 codegen isolation.
  - `docs/api/conventions.md`: the client developer's reference (problem codes table, pagination, idempotency, rate limits, clock sync).
  - Runbook: `hv api`, `hv openapi`, Grafana traces.
- [ ] Commit `docs: add ADR-0010 API conventions`, then finish the branch: green CI, fast-forward, delete the branch.

## Problem codes introduced here

| Code | Status | When |
|---|---|---|
| `bad-request` | 400 | Generic client error |
| `host-not-allowed` | 400 | `Host` not in `HV_API_ALLOWED_HOSTS` |
| `invalid-cursor` | 400 | Tampered, stale or foreign pagination cursor |
| `idempotency-key-missing` / `idempotency-key-invalid` | 400 | Create without a usable `Idempotency-Key` |
| `not-found` | 404 | Unknown path (and later, resources outside your scope) |
| `method-not-allowed` | 405 | Wrong method; `Allow` lists the right ones |
| `idempotency-request-in-progress` | 409 | The same key is still being processed |
| `payload-too-large` | 413 | Body over `HV_API_MAX_BODY_BYTES` |
| `validation-failed` | 422 | Schema validation; `errors[]` has `pointer`/`parameter`/`header` |
| `idempotency-key-reused` | 422 | Same key, different request |
| `rate-limited` | 429 | With `Retry-After` and `RateLimit` headers |
| `internal-error` | 500 | Unhandled error; details only in logs and traces |
| `service-unavailable` | 503 | A dependency is down (readiness, fail-closed limits) |

## Self-review

- **Spec coverage** (master plan SP-01 deliverables left after SP-01a):
  - RFC 9457 errors (Task 1);
  - pagination (Task 2);
  - idempotency (Task 3);
  - rate-limit middleware (Task 4);
  - OpenTelemetry (Task 5);
  - clock sync and the OpenAPI → TypeScript client pipeline (Task 6);
  - §5.4 health probes and a containerised service (Tasks 1 and 7).
- **Handed on:**
  - SP-01c: storage and the URL signer, the AI provider layer with `ai_invocations`, and metering over `usage_events`.
  - SP-02: the authenticated principal, and with it the `by_principal` / `by_organization` rate-limit keys and the idempotency `scope`.
  - SP-08: the Rust `api-client` crate reads the same `openapi.json`.
  - Worker SP: scheduling `purge_idempotency_keys` (24 h).
- **Type consistency:**
  - `ProblemError` / `problem_type` / `Page` / `PageParams` / `paginate` / `Idempotency.run` / `RateRule` / `RateLimiter.hit` / `setup_telemetry` are named the same in every task.
  - `ServerTime` fields match `ClockSample` (`t1 = received_at_ms`, `t2 = sent_at_ms`).
