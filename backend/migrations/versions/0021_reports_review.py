"""Reports, review and the hiring workflow (SP-17; PRD §69, §71, §72, §99).

- `applications.hiring_status`: PRD §72's nine statuses beside the screening `stage`, filled from
  the stage (an invited candidate whose interview is running is `interview_started`).
- `application_status_history`, `hiring_inputs`, `candidate_notes` and `score_changes`: insert-only.
- `reports`: the candidate-visible report of an interview; `report_exports`: stored PDFs.
- `organization_settings.candidate_report`: which of PRD §99's items an organisation shares.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-17
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HIRING_STATUSES = (
    "under_review",
    "shortlisted",
    "interview_invited",
    "interview_started",
    "interview_completed",
    "additional_review",
    "selected",
    "rejected",
    "on_hold",
)
STATUS_SOURCES = ("system", "user")
RECOMMENDATIONS = ("strong_hire", "hire", "hold", "no_hire", "strong_no_hire")
SCORE_SCOPES = ("overall", "skill", "communication", "question")
REPORT_KINDS = ("interview", "proctoring", "coding", "candidate", "candidate_visible")
REPORT_AUDIENCES = ("internal", "candidate")
EXPORT_STATUSES = ("ready", "failed")
CANDIDATE_REPORT_STATUSES = ("draft", "released", "withdrawn")
NOTE_MAX = 4000


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _created() -> sa.Column[datetime]:
    """Rows written in one transaction keep their order: the clock, not the transaction's start."""
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("clock_timestamp()"),
        nullable=False,
    )


def _ts(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _jsonb(name: str, default: str) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(), server_default=sa.text(f"'{default}'::jsonb"), nullable=False
    )


def _organization_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
    )


def _composite_fk(
    table: str, column: str, target: str, ondelete: str | None = "CASCADE"
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{target}.organization_id", f"{target}.id"],
        name=op.f(f"fk_{table}_organization_id_{column}_{target}"),
        ondelete=ondelete,
    )


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return _composite_fk(table, column, "users", ondelete=None)


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("hiring_status", sa.Text(), server_default="under_review", nullable=False),
    )
    op.execute(
        "UPDATE applications SET hiring_status = CASE stage "
        "WHEN 'shortlisted' THEN 'shortlisted' WHEN 'rejected' THEN 'rejected' "
        "WHEN 'on_hold' THEN 'on_hold' WHEN 'interview' THEN 'interview_invited' "
        "WHEN 'interviewed' THEN 'interview_completed' ELSE 'under_review' END"
    )
    op.execute(
        "UPDATE applications SET hiring_status = 'interview_started' WHERE stage = 'interview' "
        "AND EXISTS (SELECT 1 FROM interviews i WHERE i.application_id = applications.id "
        "AND i.status IN ('in_progress', 'interrupted'))"
    )
    op.create_check_constraint(
        op.f("ck_applications_hiring_status"),
        "applications",
        _in("hiring_status", HIRING_STATUSES),
    )
    op.add_column("organization_settings", _jsonb("candidate_report", "{}"))

    op.create_table(
        "application_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=True),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.Boolean(), server_default=sa.false(), nullable=False),
        _created(),
        sa.CheckConstraint(
            _in("to_status", HIRING_STATUSES),
            name=op.f("ck_application_status_history_to_status"),
        ),
        sa.CheckConstraint(
            _in("source", STATUS_SOURCES), name=op.f("ck_application_status_history_source")
        ),
        _organization_fk("application_status_history"),
        _composite_fk("application_status_history", "application_id", "applications"),
        _composite_fk("application_status_history", "interview_id", "interviews"),
        _user_fk("application_status_history", "actor_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_status_history")),
    )
    op.create_index(
        "ix_application_status_history_application_id",
        "application_status_history",
        ["application_id", "created_at"],
    )
    _tenant("application_status_history", ["SELECT", "INSERT"])

    op.create_table(
        "hiring_inputs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        _jsonb("ratings", "{}"),
        sa.Column("rationale", sa.Text(), nullable=False),
        _created(),
        sa.CheckConstraint(
            _in("recommendation", RECOMMENDATIONS), name=op.f("ck_hiring_inputs_recommendation")
        ),
        sa.CheckConstraint("length(btrim(rationale)) > 0", name=op.f("ck_hiring_inputs_rationale")),
        _organization_fk("hiring_inputs"),
        _composite_fk("hiring_inputs", "application_id", "applications"),
        _composite_fk("hiring_inputs", "interview_id", "interviews"),
        _user_fk("hiring_inputs", "author_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hiring_inputs")),
    )
    op.create_index(
        "ix_hiring_inputs_application_id", "hiring_inputs", ["application_id", "created_at"]
    )
    _tenant("hiring_inputs", ["SELECT", "INSERT"])

    op.create_table(
        "candidate_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("interview_id", sa.Uuid(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("at_ms", sa.BigInteger(), nullable=True),
        _created(),
        sa.CheckConstraint(
            f"length(btrim(body)) BETWEEN 1 AND {NOTE_MAX}", name=op.f("ck_candidate_notes_body")
        ),
        sa.CheckConstraint("at_ms IS NULL OR at_ms >= 0", name=op.f("ck_candidate_notes_at_ms")),
        _organization_fk("candidate_notes"),
        _composite_fk("candidate_notes", "candidate_id", "candidates"),
        _composite_fk("candidate_notes", "application_id", "applications"),
        _composite_fk("candidate_notes", "interview_id", "interviews"),
        _user_fk("candidate_notes", "author_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_notes")),
    )
    op.create_index(
        "ix_candidate_notes_candidate_id", "candidate_notes", ["candidate_id", "created_at"]
    )
    op.create_index(
        "ix_candidate_notes_interview_id", "candidate_notes", ["interview_id", "created_at"]
    )
    _tenant("candidate_notes", ["SELECT", "INSERT"])

    op.create_table(
        "score_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("previous_score", sa.Numeric(4, 2), nullable=True),
        sa.Column("new_score", sa.Numeric(4, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=False),
        _created(),
        sa.CheckConstraint(_in("scope", SCORE_SCOPES), name=op.f("ck_score_changes_scope")),
        sa.CheckConstraint("new_score BETWEEN 0 AND 10", name=op.f("ck_score_changes_new_score")),
        sa.CheckConstraint("length(btrim(reason)) > 0", name=op.f("ck_score_changes_reason")),
        sa.CheckConstraint(
            "(scope IN ('overall', 'communication')) = (target IS NULL)",
            name=op.f("ck_score_changes_target"),
        ),
        _organization_fk("score_changes"),
        _composite_fk("score_changes", "interview_id", "interviews"),
        _composite_fk("score_changes", "evaluation_id", "evaluations"),
        _user_fk("score_changes", "changed_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_changes")),
    )
    op.create_index(
        "ix_score_changes_interview_id", "score_changes", ["interview_id", "created_at"]
    )
    _tenant("score_changes", ["SELECT", "INSERT"])

    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        _jsonb("items", "{}"),
        sa.Column("released_items", postgresql.JSONB(), nullable=True),
        sa.Column("evaluation_id", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        _ts("approved_at"),
        sa.Column("withdrawn_by", sa.Uuid(), nullable=True),
        _ts("withdrawn_at"),
        sa.Column("withdrawn_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            _in("status", CANDIDATE_REPORT_STATUSES), name=op.f("ck_reports_status")
        ),
        sa.CheckConstraint(
            "status <> 'released' OR (released_items IS NOT NULL AND approved_by IS NOT NULL)",
            name=op.f("ck_reports_released"),
        ),
        _organization_fk("reports"),
        _composite_fk("reports", "interview_id", "interviews"),
        _composite_fk("reports", "application_id", "applications"),
        _user_fk("reports", "approved_by"),
        _user_fk("reports", "withdrawn_by"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_reports_organization_id_id")),
        sa.UniqueConstraint("interview_id", name=op.f("uq_reports_interview_id")),
    )
    _tenant("reports", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "report_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), server_default="internal", nullable=False),
        sa.Column("interview_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("candidate_account_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default="ready", nullable=False),
        sa.Column("blob_path", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), server_default="application/pdf", nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("document_sha256", sa.Text(), nullable=False),
        sa.Column("renderer", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), server_default="en-IN", nullable=False),
        _created(),
        sa.CheckConstraint(_in("kind", REPORT_KINDS), name=op.f("ck_report_exports_kind")),
        sa.CheckConstraint(
            _in("audience", REPORT_AUDIENCES), name=op.f("ck_report_exports_audience")
        ),
        sa.CheckConstraint(_in("status", EXPORT_STATUSES), name=op.f("ck_report_exports_status")),
        sa.CheckConstraint(
            "interview_id IS NOT NULL OR candidate_id IS NOT NULL",
            name=op.f("ck_report_exports_subject"),
        ),
        _organization_fk("report_exports"),
        _composite_fk("report_exports", "interview_id", "interviews"),
        _composite_fk("report_exports", "candidate_id", "candidates"),
        _user_fk("report_exports", "requested_by"),
        _composite_fk("report_exports", "candidate_account_id", "candidate_accounts"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_exports")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_report_exports_organization_id_id")
        ),
    )
    op.create_index(
        "ix_report_exports_interview_id", "report_exports", ["interview_id", "created_at"]
    )
    op.create_index(
        "ix_report_exports_candidate_id", "report_exports", ["candidate_id", "created_at"]
    )
    _tenant("report_exports", ["SELECT", "INSERT"])


def downgrade() -> None:
    for table in (
        "report_exports",
        "reports",
        "score_changes",
        "candidate_notes",
        "hiring_inputs",
        "application_status_history",
    ):
        op.drop_table(table)
    op.drop_column("organization_settings", "candidate_report")
    op.drop_constraint(op.f("ck_applications_hiring_status"), "applications", type_="check")
    op.drop_column("applications", "hiring_status")
