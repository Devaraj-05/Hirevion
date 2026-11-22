"""The laptop that started an interview (C8-9; ADR-0049).

`interview_sessions.device_jkt` holds the thumbprint of the DPoP key whose session token started
the interview. Under a `same_device` resume policy only that laptop may rejoin it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("interview_sessions", sa.Column("device_jkt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_sessions", "device_jkt")
