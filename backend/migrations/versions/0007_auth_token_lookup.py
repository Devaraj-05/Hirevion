"""The emailed-token lookup: find a single-use token by its hash before the tenant is known.

Like the sign-in lookups (0006), it belongs to `hirevion_auth`, which may read `auth_tokens`
through a read-only, all-rows policy; the application role may only execute it.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01
"""

from collections.abc import Sequence

from alembic import op

from hirevion_core.db.rls import grant_sql
from hirevion_core.settings import APP_ROLE, AUTH_ROLE

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOOKUP_SQL = """
CREATE FUNCTION auth_token(p_token_hash bytea, p_purpose text)
RETURNS TABLE (
    token_id uuid, organization_id uuid, user_id uuid, expires_at timestamptz,
    used_at timestamptz, new_email citext
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT t.id, t.organization_id, t.user_id, t.expires_at, t.used_at, t.new_email
    FROM auth_tokens t
    WHERE t.token_hash = p_token_hash AND t.purpose = p_purpose
$$
"""

FUNCTION = "auth_token(bytea, text)"


def upgrade() -> None:
    op.execute(grant_sql("auth_tokens", ["SELECT"], role=AUTH_ROLE))
    op.execute(
        f"CREATE POLICY auth_tokens_auth_lookup ON auth_tokens FOR SELECT TO {AUTH_ROLE} "
        "USING (true)"
    )
    op.execute(LOOKUP_SQL)
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}")
    op.execute("DROP POLICY IF EXISTS auth_tokens_auth_lookup ON auth_tokens")
    op.execute(f"REVOKE SELECT ON auth_tokens FROM {AUTH_ROLE}")  # noqa: S608 (a constant)
