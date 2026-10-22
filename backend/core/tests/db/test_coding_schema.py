"""The coding tables (SP-16, migration 0022): every submission and every integrity event is kept,
tenant-scoped and insert-only, and an event never carries the text the candidate pasted."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import CodingSubmission, CodingTelemetry, InterviewQuestion

from .test_interviews_schema import insert_interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
NOW = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


async def coding_question(
    app_db: Database, admin_engine: AsyncEngine, make_hiring: Any, org: UUID
) -> tuple[UUID, UUID]:
    """An interview in progress with an open coding question: (interview, question)."""
    hiring = await make_hiring(org)
    interview = await insert_interview(admin_engine, hiring, status="in_progress")
    question = uuid7()
    async with app_db.tenant(org) as session:
        session.add(
            InterviewQuestion(
                id=question,
                organization_id=org,
                interview_id=interview,
                position=5,
                kind="coding",
                stage="coding",
                skill="Python",
                type="coding",
                text="Write a function that returns the two indices adding up to a target.",
                source="library",
                workspace="code",
                languages=["python", "javascript"],
                status="asked",
                asked_at=NOW,
            )
        )
    return interview, question


def submission(org: UUID, interview: UUID, question: UUID, **changes: Any) -> CodingSubmission:
    fields: dict[str, Any] = {
        "organization_id": org,
        "interview_id": interview,
        "question_id": question,
        "language": "python",
        "code": "def solve(nums, target):\n    return []\n",
        "size": 39,
        "sha256": "0" * 64,
        "source": "submitted",
    }
    return CodingSubmission(**{**fields, **changes})


def telemetry(org: UUID, interview: UUID, question: UUID, **changes: Any) -> CodingTelemetry:
    fields: dict[str, Any] = {
        "organization_id": org,
        "interview_id": interview,
        "question_id": question,
        "kind": "paste",
        "chars": 120,
        "occurred_at": NOW,
    }
    return CodingTelemetry(**{**fields, **changes})


async def test_coding_tables_are_tenant_scoped(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    for org in (acme, globex):
        interview, question = await coding_question(app_db, admin_engine, make_hiring, org)
        async with app_db.tenant(org) as session:
            session.add(submission(org, interview, question))
            session.add(telemetry(org, interview, question))
    async with app_db.tenant(acme) as session:
        for model in (CodingSubmission, CodingTelemetry):
            rows = (await session.scalars(select(model))).all()
            assert [row.organization_id for row in rows] == [acme], model


async def test_submissions_and_telemetry_are_insert_only(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview, question = await coding_question(app_db, admin_engine, make_hiring, org)
    async with app_db.tenant(org) as session:
        session.add(submission(org, interview, question))
        session.add(telemetry(org, interview, question))
    for statement in (
        "UPDATE coding_submissions SET code = 'edited'",
        "DELETE FROM coding_submissions",
        "UPDATE coding_telemetry SET chars = 1",
        "DELETE FROM coding_telemetry",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with app_db.tenant(org) as session:
                await session.execute(text(statement))


@pytest.mark.parametrize(
    "changes",
    [
        {"language": "cobol"},
        {"source": "guessed"},
        {"size": -1},
        {"sha256": "short"},
    ],
)
async def test_a_submission_keeps_to_the_known_values(
    changes: dict[str, Any],
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview, question = await coding_question(app_db, admin_engine, make_hiring, org)
    with pytest.raises(IntegrityError):
        async with app_db.tenant(org) as session:
            session.add(submission(org, interview, question, **changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "keystroke"},
        {"kind": "paste", "chars": None},
        {"kind": "focus", "chars": 3},
        {"kind": "copy", "chars": -5},
    ],
)
async def test_an_event_is_one_of_the_kinds_and_only_a_clipboard_event_has_a_length(
    changes: dict[str, Any],
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    interview, question = await coding_question(app_db, admin_engine, make_hiring, org)
    with pytest.raises(IntegrityError):
        async with app_db.tenant(org) as session:
            session.add(telemetry(org, interview, question, **changes))


async def test_there_is_no_column_for_pasted_text(admin_engine: AsyncEngine) -> None:
    async with admin_engine.connect() as conn:
        columns = set(
            (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'coding_telemetry'"
                    )
                )
            ).scalars()
        )
    assert columns == {
        "id",
        "organization_id",
        "interview_id",
        "question_id",
        "kind",
        "chars",
        "occurred_at",
        "received_at",
    }
