"""The catalog audit behind the tenant-isolation harness (SP-01 exit criterion).

It reports every way one tenant's rows could reach another through the application roles:

- a tenant table (one with `organization_id`, or `organizations`) whose row-level security is
  not enabled, not forced, or has no policy;
- a table owned by an application role (an owner can switch its RLS off);
- a partition an application role can query directly (a partition doesn't apply its parent's
  policies when it is queried by name);
- an application role that is a superuser or bypasses RLS. This includes `hirevion_auth`, which
  owns the sign-in lookup functions and so must stay unable to see past its narrow policies.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from hirevion_core.settings import APP_ROLE, AUTH_ROLE, RELAY_ROLE

_APP_ROLES = [APP_ROLE, RELAY_ROLE, AUTH_ROLE]

_TENANT_TABLES = text(
    """
    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
           EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) AS has_policy
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
      AND NOT c.relispartition
      AND (c.relname = 'organizations' OR EXISTS (
            SELECT 1 FROM pg_attribute a
            WHERE a.attrelid = c.oid AND a.attname = 'organization_id' AND NOT a.attisdropped))
    ORDER BY c.relname
    """
)

_ROLES = text(
    "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
    "WHERE rolname = ANY(:roles) ORDER BY rolname"
)

_OWNED = text(
    """
    SELECT c.relname, pg_get_userbyid(c.relowner) AS owner
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND pg_get_userbyid(c.relowner) = ANY(:roles)
    ORDER BY c.relname
    """
)

_PARTITION_GRANTS = text(
    """
    SELECT c.relname, r.rolname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN pg_roles r
    WHERE n.nspname = 'public'
      AND c.relispartition
      AND r.rolname = ANY(:roles)
      AND has_table_privilege(r.oid, c.oid, 'SELECT, INSERT, UPDATE, DELETE')
    ORDER BY c.relname, r.rolname
    """
)


async def find_isolation_problems(conn: AsyncConnection) -> list[str]:
    """Every isolation problem in the `public` schema, as readable messages; empty when sound."""
    problems: list[str] = []
    for name, enabled, forced, has_policy in await conn.execute(_TENANT_TABLES):
        if not enabled:
            problems.append(f"{name}: row-level security is not enabled")
        if not forced:
            problems.append(f"{name}: row-level security is not forced")
        if not has_policy:
            problems.append(f"{name}: has no row-level security policy")

    roles = {"roles": _APP_ROLES}
    for role, superuser, bypass in await conn.execute(_ROLES, roles):
        if superuser:
            problems.append(f"{role}: is a superuser")
        if bypass:
            problems.append(f"{role}: bypasses row-level security")
    for name, owner in await conn.execute(_OWNED, roles):
        problems.append(f"{name}: owned by {owner}, which could switch row-level security off")
    for name, role in await conn.execute(_PARTITION_GRANTS, roles):
        problems.append(f"{name}: partition is directly accessible to {role}")
    return problems
