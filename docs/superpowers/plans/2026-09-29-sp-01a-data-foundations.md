# SP-01a Data Foundations and Tenancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared `hirevion_core` data layer: typed settings, UUIDv7 keys, an async PostgreSQL session that is always tenant-scoped through row-level security, the Alembic baseline with the SP-01 core tables, the hash-chained audit log and the transactional outbox published to Valkey Streams. A tenant-isolation harness and an outbox delivery test gate it.

**Architecture:**

- **Package.** A new uv workspace member, `backend/core` (package `hirevion_core`), holds settings, ids, the database layer, models, the audit service and the outbox. Alembic migrations live in `backend/migrations` and are written by hand, because RLS policies, partitions and grants don't autogenerate. A test keeps the ORM models and the migrations in agreement.
- **Roles.** The application never connects as a superuser or a table owner:
  - `hirevion_app` is subject to row-level security;
  - `hirevion_relay` is allowed only to publish outbox rows;
  - the admin role (`POSTGRES_USER`) runs migrations.

  `uv run hv migrate` creates or updates the two roles, applies migrations and creates the upcoming monthly partitions.
- **Tenant scoping.** Every tenant table has `organization_id`, RLS that is *enabled and forced*, and a policy comparing it with `current_setting('app.org_id')`. That setting is transaction-local (`set_config(..., true)`), so pooled connections can't leak a tenant.

**Tech Stack:** Python 3.12, SQLAlchemy 2 (async) + asyncpg, Alembic, pydantic-settings, redis-py (asyncio) against Valkey 8, pytest + pytest-asyncio against the real PostgreSQL 17 / Valkey from `hv up` (service containers in CI).

## Global Constraints

- Everything in `MASTER_IMPLEMENTATION_PLAN.md` §13 applies: UUIDv7 keys and UTC `timestamptz`; `organization_id` on every tenant row; RLS bound to `app.org_id`; monthly partitions for `audit_logs` and `usage_events`; the audit log is append-only and hash-chained per organisation; TDD; ≥ 85 % line coverage on domain modules.
- Tenant isolation fails closed. With no `app.org_id` set, tenant tables return no rows and accept no writes.
- Secrets come only from the gitignored root `.env` (`hv init-env` / `hv env-sync` generate them). No password appears in a migration, a log or an error message.
- Database tests run against real PostgreSQL and Valkey, never mocks. Locally the target is the `hirevion_test` database; in CI, service containers.
- The outbox is at-least-once: the relay may publish an event twice after a crash, so consumers de-duplicate on the event id.

## File Structure

| Path | Responsibility |
|---|---|
| `backend/core/pyproject.toml` | Package `hirevion-core` |
| `backend/core/src/hirevion_core/settings.py` | `CoreSettings`: database and Valkey connection settings for each role, read from the root `.env` |
| `backend/core/src/hirevion_core/ids.py` | `uuid7()` (RFC 9562) and `uuid7_time()` |
| `backend/core/src/hirevion_core/db/base.py` | Declarative `Base`, naming conventions, `IdMixin`, `TimestampMixin`, `TenantMixin` |
| `backend/core/src/hirevion_core/db/session.py` | `Database` with `tenant(org_id)` and `unscoped()` session scopes |
| `backend/core/src/hirevion_core/db/rls.py` | SQL for tenant policies and grants (used by migrations) |
| `backend/core/src/hirevion_core/db/partitions.py` | Monthly partition ranges (pure) and `ensure_monthly_partitions()` |
| `backend/core/src/hirevion_core/db/roles.py` | `bootstrap_roles()`: create or update the app and relay roles |
| `backend/core/src/hirevion_core/db/isolation.py` | `find_isolation_problems()`: the catalog audit behind the harness |
| `backend/core/src/hirevion_core/db/migrate.py` | `migrate()`: bootstrap roles, `alembic upgrade head`, partitions |
| `backend/core/src/hirevion_core/models/*.py` | `Organization`, `FeatureFlag`, `AuditLog`, `OutboxEvent`, `UsageEvent` |
| `backend/core/src/hirevion_core/audit.py` | `AuditService.append()` and `verify_chain()`; `canonical_json()`, `chain_hash()` |
| `backend/core/src/hirevion_core/outbox.py` | `publish_event()` and `OutboxRelay` (Valkey Streams) |
| `backend/core/tests/**` | Unit tests plus `db`-marked integration tests |
| `backend/migrations/{alembic.ini,env.py,script.py.mako,versions/0001_baseline.py}` | The Alembic baseline |
| `tools/devcli/src/hirevion_devcli/cli.py` | `hv migrate [--database NAME]` |
| `tools/devcli/src/hirevion_devcli/envfile.py`, `.env.example` | `POSTGRES_APP_PASSWORD`, `POSTGRES_RELAY_PASSWORD` |
| `.github/workflows/ci.yml` | PostgreSQL and Valkey service containers for the Python job |
| `docs/architecture/adr/0009-tenancy-and-data-foundations.md` | The decisions above |

---

### Task 1: Package, settings and UUIDv7

**Interfaces:**

- Produces: the constants `APP_ROLE = "hirevion_app"` and `RELAY_ROLE = "hirevion_relay"`.
- Produces: `load_core_settings() -> CoreSettings`.
- Produces: `CoreSettings.database_url(role: Literal["admin", "app", "relay"], database: str | None = None) -> str`, an asyncpg URL with the password URL-encoded.
- Produces: `CoreSettings.valkey_url() -> str` (no auth part when the password is empty).
- Produces: `uuid7(now_ms: int | None = None, rand: bytes | None = None) -> UUID` and `uuid7_time(value: UUID) -> datetime`.

- [x] Add the workspace member `backend/core` (deps: `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `alembic`, `pydantic-settings>=2.4`, `redis>=5`). Add `pytest-asyncio` to the dev group, and add `backend/core/tests` to `testpaths` with `asyncio_mode = "auto"` and a `db` marker.
- [x] Tests first (`tests/test_ids.py`), covering:
  - version 7 and the RFC variant;
  - the timestamp round-trips through `uuid7_time`;
  - a later millisecond sorts after an earlier one;
  - fixed `rand` gives a fixed value;
  - 10,000 calls are unique.
- [x] Tests first (`tests/test_settings.py`), covering:
  - URLs for all three roles;
  - a password containing `@:/` is escaped;
  - the Valkey URL with and without a password;
  - a missing required password names the key but never its value;
  - `repr` contains no secret.
- [x] Implement both modules:

```python
# ids.py
def uuid7(now_ms: int | None = None, rand: bytes | None = None) -> UUID:
    ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    entropy = os.urandom(10) if rand is None else rand
    value = (ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76
    value |= (int.from_bytes(entropy[:2], "big") & 0x0FFF) << 64
    value |= 0b10 << 62
    value |= int.from_bytes(entropy[2:10], "big") & ((1 << 62) - 1)
    return UUID(int=value)
```

- [x] Add `POSTGRES_APP_PASSWORD` and `POSTGRES_RELAY_PASSWORD` (32 characters each) to `GENERATED_KEYS` and `.env.example`. Extend the devcli tests. Run `uv run hv env-sync`.
- [x] Commit `feat(core): add core settings and UUIDv7 ids`.

### Task 2: Base models, tenant sessions, roles and the Alembic baseline

**Interfaces:**

- Produces: `Database(engine)` with two session scopes:
  - `async with db.tenant(org_id) as session:` opens a transaction and sets `app.org_id` for it only;
  - `async with db.unscoped() as session:` opens a transaction with no tenant.
- Produces: `create_database(settings, role, database=None) -> Database`.
- Produces: `tenant_policy_sql(table) -> list[str]`.
- Produces: `bootstrap_roles(conn, database, app_password, relay_password) -> None`.
- Produces: `migrate(settings, database) -> None`.
- Produces: `find_isolation_problems(conn) -> list[str]`, which is empty when isolation holds.

- [x] Tests first:
  - Pure tests:
    - `tenant_policy_sql("jobs")` produces ENABLE, FORCE, and a policy `TO hirevion_app` using `NULLIF(current_setting('app.org_id', true), '')::uuid`;
    - invalid identifiers raise.
  - DB-marked integration tests (a session fixture resets `public` in `hirevion_test` and runs `migrate()`):
    1. The harness: `find_isolation_problems` returns `[]` for the baseline. After `CREATE TABLE leaky (id uuid, organization_id uuid)` it reports `leaky`: RLS disabled, not forced, no policy.
    2. Roles: `hirevion_app` is not a superuser, lacks `BYPASSRLS`, and owns no table.
    3. Isolation behaviour: an organisation inserted as admin is visible in `db.tenant(its_id)` and invisible in `db.tenant(other_id)` and in `db.unscoped()`.
    4. No leak through the pool: after a tenant session, the next `unscoped()` session on the same engine sees nothing.
- [x] Implement `db/base.py`:
  - naming conventions `pk_%(table_name)s`, `fk_…`, `ix_…`, `uq_…`, `ck_…`;
  - `IdMixin` (`id: Mapped[UUID]`, primary key, `default=uuid7`);
  - `TimestampMixin` (`created_at`, `updated_at`, `timestamptz`, server default `now()`);
  - `TenantMixin` (`organization_id`, not null, indexed, FK to `organizations.id`).
- [x] Implement `db/session.py`:

```python
@asynccontextmanager
async def tenant(self, organization_id: UUID) -> AsyncIterator[AsyncSession]:
    async with self._sessions() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.org_id', :org, true)"), {"org": str(organization_id)}
        )
        yield session
```

- [x] Implement `db/roles.py`:
  - passwords must match `^[A-Za-z0-9_-]{24,}$`, because DDL can't take bind parameters;
  - `CREATE ROLE` / `ALTER ROLE … LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD '…'`;
  - `GRANT CONNECT ON DATABASE`, `GRANT USAGE ON SCHEMA public`.
- [x] Implement `db/isolation.py`. It queries `pg_class`/`pg_attribute`/`pg_policy` in `public` for:
  - every ordinary or partitioned table (not partitions) that has an `organization_id` column, or is named `organizations`, and lacks `relrowsecurity`, `relforcerowsecurity` or at least one policy;
  - any table owned by the app role;
  - any partition the app or relay role holds privileges on.
- [x] Alembic (`backend/migrations`): an async `env.py` whose URL comes from `CoreSettings.database_url("admin", database)` (override: `-x database=NAME`). Baseline `0001`:
  - extensions `vector`, `pg_trgm`, `citext`;
  - `ALTER DEFAULT PRIVILEGES … GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hirevion_app`;
  - `organizations`: `id`, `name`, `slug citext unique`, `status`, `created_at`, `updated_at`. RLS policy `id = current org`; app role `SELECT` and `UPDATE` only (creation is a platform action, SP-02/22).
  - `feature_flags`: `id`, `key`, `organization_id` nullable, `enabled`, `rollout_percent`, `description`, timestamps; unique `(key, organization_id)`. RLS read policy `organization_id IS NULL OR organization_id = current org`; app role `SELECT` only.
- [x] Implement `db/migrate.py` (bootstrap roles, then `alembic.command.upgrade`, then `ensure_monthly_partitions` for 3 months ahead) and `hv migrate [--database hirevion]`.
- [x] Commit `feat(core): add tenant-scoped sessions, roles and the Alembic baseline`.

### Task 3: Monthly partitions and the hash-chained audit log

**Interfaces:**

- Produces: `month_ranges(start: date, months: int) -> list[tuple[str, date, date]]`, returning `("y2026m09", 2026-09-01, 2026-10-01)`, and so on.
- Produces: `ensure_monthly_partitions(conn, table, start, months) -> list[str]`, the partitions it created.
- Produces: `AuditEntry(action, resource_type, resource_id=None, actor_type="system", actor_id=None, ip=None, user_agent=None, details=…)`.
- Produces: `AuditService.append(session, organization_id, entry, now=None) -> AuditLog`.
- Produces: `AuditService.verify_chain(session, organization_id) -> ChainCheck(ok: bool, checked: int, first_bad_seq: int | None)`.
- Produces: `canonical_json(record: dict) -> bytes` and `chain_hash(prev: bytes, record: dict) -> bytes`.

- [x] Tests first:
  - Pure tests:
    - `month_ranges` across a year boundary;
    - `canonical_json` is key-order independent and UTF-8 exact;
    - `chain_hash` equals `sha256(prev + canonical_json(record))`;
    - the genesis hash is 32 zero bytes.
  - DB tests:
    1. Three appends give `seq` 1, 2, 3 with linked hashes, and `verify_chain.ok`.
    2. An admin `UPDATE` that bypasses the trigger (with the trigger temporarily disabled by the admin in the test) makes `verify_chain` report the tampered `seq`.
    3. As the app role, `UPDATE` and `DELETE` on `audit_logs` fail with permission denied.
    4. 20 concurrent appends for one organisation (`asyncio.gather` across separate sessions) produce `seq` 1–20 and a valid chain.
    5. An organisation can't read another organisation's audit rows.
    6. A row dated in 2030 lands in the default partition and is still readable.
- [x] Migration `0002_audit_logs`, partitioned `BY RANGE (occurred_at)`:
  - columns: `id`, `organization_id`, `seq bigint`, `occurred_at`, `actor_type`, `actor_id`, `action`, `resource_type`, `resource_id`, `ip inet`, `user_agent`, `details jsonb`, `prev_hash bytea`, `hash bytea`;
  - PK `(id, occurred_at)`; index `(organization_id, seq DESC)`;
  - a DEFAULT partition;
  - RLS (tenant policy);
  - `REVOKE UPDATE, DELETE` from the app role;
  - a `BEFORE UPDATE OR DELETE` trigger that raises. Retention drops whole partitions (SP-22), which fires no row trigger.
- [x] Implement `audit.py`. `append` takes `pg_advisory_xact_lock(hashtextextended('audit:' || org, 0))`, reads the last `(seq, hash)` for the organisation, computes the next values and inserts. `occurred_at` is generated in Python (UTC, microseconds), so the hashed value is exactly the stored one.
- [x] Commit `feat(core): add monthly partitions and the hash-chained audit log`.

### Task 4: Outbox, relay to Valkey Streams, usage events

**Interfaces:**

- Produces: `publish_event(session, organization_id, topic, payload, key=None) -> UUID`. It inserts into `outbox_events` inside the caller's transaction.
- Produces: `stream_name(topic) -> str`, which gives `"hv:events:<topic>"`. Topics match `^[a-z][a-z0-9_.-]{1,62}$`.
- Produces: `OutboxRelay(db: Database, redis, batch=100, maxlen=100_000)` with `run_once() -> int` (events published) and `run_forever(stop: asyncio.Event, poll=0.5)`.

- [x] Tests first:
  - Pure tests: `stream_name` validation.
  - DB + Valkey tests (the "outbox delivery test"):
    1. `publish_event` in a committed tenant transaction; `relay.run_once()` returns 1, and a consumer group reads one entry with the same `id`, `org`, `topic` and payload; `published_at` is set.
    2. `publish_event` in a transaction that rolls back; `run_once()` returns 0 and the stream is empty.
    3. Two relays running at once publish each event exactly once (`FOR UPDATE SKIP LOCKED`).
    4. The relay role can't read `audit_logs` (permission denied).
    5. The app role can't read another organisation's outbox rows.
- [x] Migration `0003_outbox_and_usage`:
  - `outbox_events`:
    - columns: `id`, `organization_id`, `topic`, `key`, `payload jsonb`, `created_at`, `published_at`, `attempts`;
    - partial index on unpublished rows;
    - RLS tenant policy for the app role (`SELECT` and `INSERT` only);
    - `CREATE POLICY outbox_relay ON outbox_events TO hirevion_relay USING (true)`;
    - relay grants `SELECT`, `UPDATE (published_at, attempts)` and `DELETE`.
  - `usage_events`:
    - columns: `id`, `organization_id`, `occurred_at`, `meter`, `quantity numeric`, `unit`, `source`, `attributes jsonb`;
    - partitioned monthly, with a DEFAULT partition;
    - RLS; app role `SELECT` and `INSERT`.
- [x] Implement `outbox.py`. The relay uses the relay role's `unscoped()` session:
  - `select … where published_at is null order by created_at limit :batch for update skip locked`;
  - `XADD` with fields `id`, `org`, `topic`, `key`, `payload`, `created_at`, and `MAXLEN ~`;
  - then set `published_at`.
- [x] Commit `feat(core): add the transactional outbox and Valkey stream relay`.

### Task 5: CI, models-versus-migrations check, docs

- [x] Add a test that compares `Base.metadata` with the migrated schema (`alembic.autogenerate.compare_metadata`, ignoring partitions, RLS and triggers); the difference must be empty.
- [x] CI Python job:
  - service containers `pgvector/pgvector:pg17` (pinned digest; env `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB=hirevion_test`) and `valkey/valkey:8` (pinned digest, no password);
  - health options;
  - env for `POSTGRES_*`, `POSTGRES_APP_PASSWORD`, `POSTGRES_RELAY_PASSWORD`, `VALKEY_HOST`.
- [x] Write ADR-0009 (tenancy and data foundations), and add a runbook section on `hv migrate`, the roles and running the DB tests.
- [x] Commit `docs: add ADR-0009 tenancy and data foundations`, then finish the branch: green CI, fast-forward, delete the branch.

## Self-review

- **Spec coverage** (master plan SP-01 deliverables in this plan):
  - `hirevion_core` settings, async database, RLS context and base conventions (Tasks 1–2);
  - the Alembic baseline with `organizations`, `audit_logs`, `outbox_events`, `usage_events` and `feature_flags` (Tasks 2–4);
  - the outbox publishing to Valkey (Redis) Streams (Task 4);
  - the hash-chained audit service (Task 3);
  - the exit criteria: the isolation harness (Task 2) and the outbox delivery test (Task 4).
- **Moved elsewhere:**
  - SP-01b: API conventions (RFC 9457, pagination, idempotency, rate limits), the clock-sync endpoint, OpenTelemetry and the OpenAPI → TypeScript client.
  - SP-01c: storage and the URL signer, the AI provider layer with `ai_invocations`, and the metering API over `usage_events`.
- **Type consistency:** `Database.tenant` / `unscoped` and `publish_event` / `OutboxRelay` use the same names in every task.

## Implementation notes

Where the build differs from the steps above (ADR-0009 records the reasons):

- **Role passwords** reach PostgreSQL as SCRAM-SHA-256 verifiers computed in Python (`scram_verifier()`), not as clear-text `PASSWORD` literals. The `[A-Za-z0-9_-]{24,}` rule still applies.
- **No default privileges.** Every table is granted explicitly with `grant_sql()`, so a new table or partition is reachable by nobody until a migration says so.
- **Audit index** is `(organization_id, seq)`; a B-tree scans it backwards for the latest `seq`, so `DESC` isn't needed.
- **pytest runs with `--import-mode=importlib`**, because two packages have a `test_settings.py`.
