# ADR-0009: Tenancy, audit log and outbox on PostgreSQL

- **Status:** Accepted
- **Date:** 2026-09-29
- **Sub-project:** SP-01a

## Context

Every recruiter-facing record belongs to one organisation, and one organisation must never see another's data (PRD §81, master plan §7 and §13). Authorisation checks in application code can be forgotten in a single query. The audit log must be append-only and show tampering (PRD §97, master plan §9). Domain events such as `interview.completed` must reach realtime alerts, webhooks and workers exactly when the change they describe commits (master plan D12). Metering needs a durable per-tenant record of usage (master plan §11). All of this has to run the same way on the local stack, in CI and later on Azure Database for PostgreSQL.

## Decision

- **Row-level security is the tenant boundary.**
  - Every tenant table has `organization_id`, RLS that is enabled *and forced*, and a policy comparing it with `NULLIF(current_setting('app.org_id', true), '')::uuid`.
  - `Database.tenant(org_id)` sets `app.org_id` with `set_config(..., true)`, which lasts only until the transaction ends. A pooled connection never carries a tenant into the next session.
  - With no tenant set, tenant tables look empty and refuse writes: isolation fails closed.
- **Three database roles.**
  - The services connect as `hirevion_app`, which RLS always applies to.
  - The outbox relay connects as `hirevion_relay`. Its own policy lets it read every organisation's outbox, and a column grant lets it change only `published_at` and `attempts`.
  - The admin role (`POSTGRES_USER`) runs migrations and owns every table.
  - The two application roles are never superusers, never `BYPASSRLS` and own nothing. `hv migrate` creates or updates them.
  - Their passwords are sent as SCRAM-SHA-256 verifiers, so the clear text never appears in a statement or a server log.
- **Tables are granted explicitly.** There are no default privileges; each migration grants exactly what the role needs. For example, the app role may `SELECT`/`UPDATE` its own `organizations` row but never create one.
- **The tenant-isolation harness.** `find_isolation_problems()` audits the catalog and runs in CI. It fails on:
  - any tenant table without enabled and forced RLS or without a policy;
  - any table owned by an application role;
  - any partition an application role can query directly (a partition queried by name skips its parent's policies);
  - an application role that is a superuser or bypasses RLS.
- **Monthly partitions** for `audit_logs` and `usage_events`, range-partitioned on `occurred_at`, each with a DEFAULT partition. `hv migrate` creates this month's and the next two months' partitions, with UTC bounds and no grants.
- **Hash-chained audit log.**
  - Each organisation has its own chain: `hash = sha256(prev_hash || canonical_json(record))`, starting from 32 zero bytes. `verify_chain()` names the first broken `seq`.
  - Appends for one organisation queue on `pg_advisory_xact_lock`, so `seq` has no gaps or duplicates.
  - The app role may only `SELECT` and `INSERT`. A trigger refuses `UPDATE` and `DELETE` even from the admin role. Retention (SP-22) drops whole partitions, which fires no row trigger.
- **Transactional outbox.**
  - `publish_event()` writes to `outbox_events` in the caller's transaction.
  - `OutboxRelay` claims batches with `FOR UPDATE SKIP LOCKED`, so several relays can run at once. It `XADD`s each event to `hv:events:<topic>` (approximate `MAXLEN`) and stamps it published.
  - Delivery is at least once: consumers de-duplicate on the event `id`. There is no ordering guarantee across transactions.
  - A failed publish leaves the event pending and increments `attempts`.
- **Migrations are hand-written Alembic revisions** in `backend/migrations`, because policies, grants, triggers and partitions don't autogenerate. A test compares the ORM models with the migrated schema so the two can't drift.
- **Keys** are UUIDv7 generated in Python (PostgreSQL 17 has no `uuidv7()`); times are `timestamptz`.

## Consequences

- **A new tenant table is not done until the harness passes.** Its migration must call `tenant_policy_sql()` and grant explicitly, and its model must match the migration.
- **Partitions need upkeep.**
  - `hv migrate` must run at least every two months, or a scheduled job must run `ensure_monthly_partitions()` (worker beat, SP-18/SP-22).
  - If rows pile up in a DEFAULT partition for a month that later gets its own partition, creating that partition fails until those rows are moved. The same job should alert on a non-empty DEFAULT partition.
- **No uniqueness across partitions.** Unique constraints on a partitioned table must include `occurred_at`, so `(organization_id, seq)` uniqueness relies on the advisory lock, and `verify_chain()` would expose a violation.
- **Platform actions across organisations** (super admin, SP-22) need their own narrowly scoped role or SECURITY DEFINER functions, audited. They must never widen `hirevion_app`.
- **Cloud Migration Plan.**
  - On Azure Flexible Server the admin role is not a superuser, so FORCE RLS applies to it as the table owner. Migrations that touch tenant rows must set `app.org_id` or run under a role granted `BYPASSRLS`.
  - The three extensions (`vector`, `pg_trgm`, `citext`) must be allow-listed on the server.
- **Tests need the real stack.** `db`-marked tests use `hirevion_test` locally (`uv run hv up`) and service containers in CI; `-m "not db"` runs the rest.
