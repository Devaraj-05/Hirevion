"""Interview configuration: the question library and interview templates, both as stable
identities with immutable versions (PRD §21, §22 and §80), and per-organisation settings holding the
interview defaults (SP-06).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-05
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from hirevion_core.db.rls import grant_sql, tenant_policy_sql

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIES = ("technical", "coding", "system_design", "resume_based", "custom")
TYPES = (
    "technical",
    "conceptual",
    "scenario",
    "system_design",
    "coding",
    "resume_based",
    "project_based",
    "problem_solving",
)
DIFFICULTIES = ("easy", "medium", "hard")
LEVELS = ("off", "basic", "standard", "strict")
THIRD_EYE = ("off", "optional", "required")


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _created() -> sa.Column[datetime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _organization_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id"],
        ["organizations.id"],
        name=op.f(f"fk_{table}_organization_id_organizations"),
    )


def _composite_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["organization_id", column],
        [f"{target}.organization_id", f"{target}.id"],
        name=op.f(f"fk_{table}_organization_id_{column}_{target}"),
        ondelete="CASCADE",
    )


def _tenant(table: str, privileges: list[str]) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    for statement in tenant_policy_sql(table):
        op.execute(statement)
    op.execute(grant_sql(table, privileges))


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _jsonb(name: str, default: str, nullable: bool = False) -> sa.Column[object]:
    if nullable:
        return sa.Column(name, postgresql.JSONB(), nullable=True)
    return sa.Column(
        name, postgresql.JSONB(), server_default=sa.text(f"'{default}'::jsonb"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("source", sa.Text(), server_default="manual", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(_in("category", CATEGORIES), name=op.f("ck_questions_category")),
        sa.CheckConstraint(
            _in("status", ("draft", "approved", "archived")), name=op.f("ck_questions_status")
        ),
        sa.CheckConstraint(_in("source", ("manual", "ai")), name=op.f("ck_questions_source")),
        _organization_fk("questions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_questions")),
        sa.UniqueConstraint("organization_id", "id", name=op.f("uq_questions_organization_id_id")),
    )
    _tenant("questions", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "question_versions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("skill_name", sa.Text(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "expected_concepts",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        _jsonb("rubric", "[]"),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=True),
        _jsonb("follow_up_rules", "[]"),
        _jsonb("coding", "", nullable=True),
        _jsonb("generation", "", nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created(),
        sa.CheckConstraint(
            _in("difficulty", DIFFICULTIES), name=op.f("ck_question_versions_difficulty")
        ),
        sa.CheckConstraint(_in("type", TYPES), name=op.f("ck_question_versions_type")),
        _organization_fk("question_versions"),
        _composite_fk("question_versions", "question_id", "questions"),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skills.id"], name=op.f("fk_question_versions_skill_id_skills")
        ),
        sa.PrimaryKeyConstraint("question_id", "version", name=op.f("pk_question_versions")),
    )
    op.create_index(
        "ix_question_versions_text_trgm",
        "question_versions",
        ["text"],
        postgresql_using="gin",
        postgresql_ops={"text": "gin_trgm_ops"},
    )
    _tenant("question_versions", ["SELECT", "INSERT"])

    op.create_table(
        "interview_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            _in("status", ("active", "archived")), name=op.f("ck_interview_templates_status")
        ),
        _organization_fk("interview_templates"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_templates")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_interview_templates_organization_id_id")
        ),
    )
    op.create_index(
        "uq_interview_templates_organization_id_name",
        "interview_templates",
        ["organization_id", sa.text("lower(name)")],
        unique=True,
    )
    _tenant("interview_templates", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "interview_template_versions",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        _jsonb("skills", "[]"),
        _jsonb("difficulty", "{}"),
        sa.Column(
            "question_types",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("use_resume", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("use_jd", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("adaptive_follow_ups", sa.Boolean(), server_default=sa.true(), nullable=False),
        _jsonb("coding", "{}"),
        sa.Column("proctoring_level", sa.Text(), server_default="standard", nullable=False),
        sa.Column("third_eye", sa.Text(), server_default="optional", nullable=False),
        _jsonb("recording", "{}"),
        _jsonb("rubric", "[]"),
        _jsonb("questions", "[]"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _created(),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 15 AND 180",
            name=op.f("ck_interview_template_versions_duration"),
        ),
        sa.CheckConstraint(
            "question_count BETWEEN 1 AND 50", name=op.f("ck_interview_template_versions_count")
        ),
        sa.CheckConstraint(
            _in("proctoring_level", LEVELS), name=op.f("ck_interview_template_versions_proctoring")
        ),
        sa.CheckConstraint(
            _in("third_eye", THIRD_EYE), name=op.f("ck_interview_template_versions_third_eye")
        ),
        _organization_fk("interview_template_versions"),
        _composite_fk("interview_template_versions", "template_id", "interview_templates"),
        sa.PrimaryKeyConstraint(
            "template_id", "version", name=op.f("pk_interview_template_versions")
        ),
    )
    _tenant("interview_template_versions", ["SELECT", "INSERT"])

    op.create_table(
        "organization_settings",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        _jsonb("interview_defaults", "{}"),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        _organization_fk("organization_settings"),
        sa.PrimaryKeyConstraint("organization_id", name=op.f("pk_organization_settings")),
    )
    for statement in tenant_policy_sql("organization_settings"):
        op.execute(statement)
    op.execute(grant_sql("organization_settings", ["SELECT", "INSERT", "UPDATE"]))


def downgrade() -> None:
    op.drop_table("organization_settings")
    op.drop_table("interview_template_versions")
    op.drop_table("interview_templates")
    op.drop_table("question_versions")
    op.drop_table("questions")
