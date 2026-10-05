"""Questions, templates and organisation settings (SP-06 Task 1)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.isolation import find_isolation_problems
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.ids import uuid7
from hirevion_core.models import InterviewTemplate, OrganizationSettings, Question

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def run(engine: AsyncEngine, sql: str, **values: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), values)


async def test_the_tables_are_tenant_scoped(
    app_db: Database, admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    for org in (acme, globex):
        question, template = uuid7(), uuid7()
        await run(
            admin_engine,
            "INSERT INTO questions (id, organization_id, category) VALUES (:id, :org, 'technical')",
            id=question,
            org=org,
        )
        await run(
            admin_engine,
            "INSERT INTO question_versions (organization_id, question_id, version, text, "
            "skill_name, difficulty, type) VALUES (:org, :id, 1, 'Why?', 'Python', 'easy', "
            "'conceptual')",
            id=question,
            org=org,
        )
        await run(
            admin_engine,
            "INSERT INTO interview_templates (id, organization_id, name) VALUES (:id, :org, 'T')",
            id=template,
            org=org,
        )
        await run(
            admin_engine,
            "INSERT INTO interview_template_versions (organization_id, template_id, version, "
            "name, duration_minutes, question_count) VALUES (:org, :id, 1, 'T', 45, 10)",
            id=template,
            org=org,
        )
        await run(
            admin_engine,
            "INSERT INTO organization_settings (organization_id) VALUES (:org)",
            org=org,
        )
    async with app_db.tenant(acme) as session:
        assert len((await session.scalars(select(Question.id))).all()) == 1
        assert len((await session.scalars(select(InterviewTemplate.id))).all()) == 1
        assert len((await session.scalars(select(OrganizationSettings.organization_id))).all()) == 1
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_db.tenant(acme) as session:
            session.add(Question(organization_id=globex, category="technical"))


async def test_template_names_are_unique_per_organisation_ignoring_case(
    admin_engine: AsyncEngine, make_organization: MakeOrganization
) -> None:
    acme = await make_organization("Acme")
    insert = "INSERT INTO interview_templates (id, organization_id, name) VALUES (:id, :org, :n)"
    await run(admin_engine, insert, id=uuid7(), org=acme, n="Senior Python")
    with pytest.raises(IntegrityError):
        await run(admin_engine, insert, id=uuid7(), org=acme, n="senior python")


def test_recruiters_manage_templates_and_questions() -> None:
    held = permissions_for(["recruiter"])
    assert {"interviews.templates.manage", "questions.manage"} <= set(held)
    assert "questions.manage" not in permissions_for(["hiring_manager"])


async def test_the_new_tables_pass_the_isolation_harness(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        assert await find_isolation_problems(conn) == []
