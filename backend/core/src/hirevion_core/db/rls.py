"""SQL for row-level security and grants, used by the migrations (ADR-0009).

Every tenant table has a policy comparing its tenant column with `app.org_id`, a
transaction-local setting that `Database.tenant()` sets. With no organisation set,
`CURRENT_ORG` is NULL and the policy matches nothing, so tenant isolation fails closed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from hirevion_core.settings import APP_ROLE

CURRENT_ORG = "NULLIF(current_setting('app.org_id', true), '')::uuid"
PRIVILEGES = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})

# Lower-case, unquoted PostgreSQL identifiers of at most 63 bytes. DDL can't take bind
# parameters, so every name spliced into SQL here must pass this first.
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def identifier(name: str) -> str:
    """`name`, if it is safe to splice into SQL unquoted; otherwise ValueError."""
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"not a safe SQL identifier: {name!r}")
    return name


def tenant_policy_sql(table: str, column: str = "organization_id") -> list[str]:
    """Enable and force RLS on `table` and let the app role reach only the current tenant's rows.

    `column` is the tenant column; `organizations` itself passes `"id"`.
    """
    table, column = identifier(table), identifier(column)
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {table}_tenant ON {table} TO {APP_ROLE} "
        f"USING ({column} = {CURRENT_ORG}) "
        f"WITH CHECK ({column} = {CURRENT_ORG})",
    ]


def grant_sql(table: str, privileges: Iterable[str], role: str = APP_ROLE) -> str:
    """A GRANT of table `privileges` to `role`. Tables are never granted by default."""
    wanted = list(privileges)
    unknown = [privilege for privilege in wanted if privilege not in PRIVILEGES]
    if unknown or not wanted:
        raise ValueError(f"unknown table privilege: {unknown or wanted}")
    return f"GRANT {', '.join(wanted)} ON {identifier(table)} TO {identifier(role)}"
