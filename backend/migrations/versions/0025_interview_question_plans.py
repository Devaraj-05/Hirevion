"""Each interview's prepared questions (C8-10; ADR-0050).

`interview_question_plans` holds the questions the worker prepared for one interview from the
job's required skills and the candidate's resume, at easy, medium and hard, checked to be
distinct. `version` rises with each top-up; the conductor merges a newer version into a running
interview's pool.
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0025"
down_revision: str | Sequence[str] | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("pending", "ready", "failed")
TABLE = "interview_question_plans"


def _ts(name: str, default: str) -> sa.Column[datetime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text(default), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("created_at", "now()"),
        _ts("updated_at", "now()"),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in STATUSES)})",
            name=op.f(f"ck_{TABLE}_status"),
        ),
        sa.CheckConstraint("version >= 0", name=op.f(f"ck_{TABLE}_version")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "interview_id"],
            ["interviews.organization_id", "interviews.id"],
            name=op.f(f"fk_{TABLE}_organization_id_interview_id_interviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("interview_id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(op.f(f"ix_{TABLE}_organization_id"), TABLE, ["organization_id"])
    for statement in tenant_policy_sql(TABLE):
        op.execute(statement)
    op.execute(grant_sql(TABLE, ["SELECT", "INSERT", "UPDATE"]))


def downgrade() -> None:
    op.drop_table(TABLE)
