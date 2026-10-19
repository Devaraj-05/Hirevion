"""D1 code review: question approval by version (SP-06; PRD §22, §23) and whether a screening
result was made blind (SP-05; master plan §3.2(1)).

`questions.approved_version`: the version a person approved. A template may pin that version or a
later one, never an earlier one: an AI draft that was edited and then approved must not have its
raw first version asked in an interview. Questions approved before this migration count as
approved from the latest version that existed when they were approved (the first, for questions
written approved).

`screening_results.blind`: whether the AI read a blind resume, so the ranking can say so. It is
null for results made before this was recorded: nobody claims what wasn't kept.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | Sequence[str] | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "screening_results",
        sa.Column("blind", sa.Boolean(), nullable=True),
    )
    op.add_column("questions", sa.Column("approved_version", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE questions q SET approved_version = COALESCE(
            (SELECT max(v.version) FROM question_versions v
              WHERE v.question_id = q.id AND v.created_at <= q.approved_at),
            1)
        WHERE q.status = 'approved'
        """
    )


def downgrade() -> None:
    op.drop_column("questions", "approved_version")
    op.drop_column("screening_results", "blind")
