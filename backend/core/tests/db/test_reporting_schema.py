"""The reports and hiring tables (SP-17, migration 0021): tenant-scoped, insert-only where the
history matters, and constrained to the values PRD §72 and §99 allow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.models import (
    Application,
    ApplicationStatusHistory,
    CandidateNote,
    HiringInput,
    Report,
    ReportExport,
    ScoreChange,
)

from .test_interviews_schema import insert_interview

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def scene(
    admin_engine: AsyncEngine, make_hiring: Any, make_user: Any, org: UUID
) -> tuple[Any, UUID, UUID, UUID]:
    """A hiring, a completed interview, an evaluation of it and a user: (hiring, interview,
    evaluation, user)."""
    hiring = await make_hiring(org)
    interview = await insert_interview(admin_engine, hiring, status="completed")
    user = await make_user(org, roles=["recruiter"])
    evaluation = uuid7()
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO evaluations (id, organization_id, interview_id, sequence, "
                "prompt_version, rubric_version, evaluation_version, status) VALUES (:id, :org, "
                ":iv, 1, 'p', 'r', 'e', 'ready')"
            ),
            {"id": evaluation, "org": org, "iv": interview},
        )
    return hiring, interview, evaluation, user


def history(org: UUID, application: UUID, **changes: Any) -> ApplicationStatusHistory:
    fields: dict[str, Any] = {
        "organization_id": org,
        "application_id": application,
        "from_status": "under_review",
        "to_status": "shortlisted",
        "source": "user",
    }
    return ApplicationStatusHistory(**{**fields, **changes})


async def test_applications_start_under_review_and_only_know_the_nine_statuses(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    hiring = await make_hiring(org)
    async with app_db.tenant(org) as session:
        application = await session.get_one(Application, hiring.application_id)
        assert application.hiring_status == "under_review"
        application.hiring_status = "additional_review"
    with pytest.raises(IntegrityError):
        async with app_db.tenant(org) as session:
            application = await session.get_one(Application, hiring.application_id)
            application.hiring_status = "hired"


async def test_the_hiring_tables_are_tenant_scoped(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    acme, globex = await make_organization("Acme"), await make_organization("Globex")
    made: dict[UUID, tuple[Any, UUID, UUID, UUID]] = {}
    for org in (acme, globex):
        made[org] = await scene(admin_engine, make_hiring, make_user, org)
        hiring, interview, _, user = made[org]
        async with app_db.tenant(org) as session:
            session.add(history(org, hiring.application_id, actor_id=user))
            session.add(
                HiringInput(
                    organization_id=org,
                    application_id=hiring.application_id,
                    author_id=user,
                    recommendation="hire",
                    rationale="Strong on PostgreSQL.",
                )
            )
            session.add(
                CandidateNote(
                    organization_id=org,
                    candidate_id=hiring.candidate_id,
                    interview_id=interview,
                    author_id=user,
                    body="Asked about indexes.",
                    at_ms=1_500,
                )
            )
    async with app_db.tenant(acme) as session:
        for model in (ApplicationStatusHistory, HiringInput, CandidateNote):
            rows = (await session.scalars(select(model))).all()
            assert [row.organization_id for row in rows] == [acme], model


async def test_status_history_inputs_notes_and_score_changes_are_insert_only(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    hiring, interview, evaluation, user = await scene(admin_engine, make_hiring, make_user, org)
    async with app_db.tenant(org) as session:
        session.add(history(org, hiring.application_id, actor_id=user))
        session.add(
            ScoreChange(
                organization_id=org,
                interview_id=interview,
                evaluation_id=evaluation,
                scope="overall",
                previous_score=Decimal("6.5"),
                new_score=Decimal("7.5"),
                reason="Second reviewer agreed the answers were stronger.",
                changed_by=user,
            )
        )
    for statement in (
        "UPDATE application_status_history SET reason = 'edited'",
        "DELETE FROM application_status_history",
        "UPDATE score_changes SET reason = 'edited'",
        "DELETE FROM score_changes",
        "UPDATE hiring_inputs SET rationale = 'edited'",
        "UPDATE candidate_notes SET body = 'edited'",
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with app_db.tenant(org) as session:
                await session.execute(text(statement))


async def test_a_score_change_needs_a_reason_a_range_and_the_right_target(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    _, interview, evaluation, user = await scene(admin_engine, make_hiring, make_user, org)

    def change(**changes: Any) -> ScoreChange:
        fields: dict[str, Any] = {
            "organization_id": org,
            "interview_id": interview,
            "evaluation_id": evaluation,
            "scope": "skill",
            "target": "PostgreSQL",
            "previous_score": Decimal("5"),
            "new_score": Decimal("7"),
            "reason": "Reviewed the recording.",
            "changed_by": user,
        }
        return ScoreChange(**{**fields, **changes})

    async with app_db.tenant(org) as session:
        session.add(change())
        session.add(change(scope="communication", target=None))
    for bad in (
        change(new_score=Decimal("10.5")),
        change(new_score=Decimal("-1")),
        change(reason="   "),
        change(target=None),  # a skill change names its skill
        change(scope="overall"),  # an overall change names nothing
        change(scope="team"),
    ):
        with pytest.raises(IntegrityError):
            async with app_db.tenant(org) as session:
                session.add(bad)


async def test_a_hiring_input_needs_a_known_recommendation_and_a_rationale(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    hiring, _, _, user = await scene(admin_engine, make_hiring, make_user, org)
    for recommendation, rationale in (("maybe", "Because."), ("hire", "  ")):
        with pytest.raises(IntegrityError):
            async with app_db.tenant(org) as session:
                session.add(
                    HiringInput(
                        organization_id=org,
                        application_id=hiring.application_id,
                        author_id=user,
                        recommendation=recommendation,
                        rationale=rationale,
                    )
                )


async def test_a_candidate_report_is_one_per_interview_and_released_only_when_approved(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    hiring, interview, evaluation, user = await scene(admin_engine, make_hiring, make_user, org)

    def report(**changes: Any) -> Report:
        fields: dict[str, Any] = {
            "organization_id": org,
            "interview_id": interview,
            "application_id": hiring.application_id,
            "evaluation_id": evaluation,
        }
        return Report(**{**fields, **changes})

    async with app_db.tenant(org) as session:
        session.add(report(items={"completion": {"text": "You completed the interview."}}))
    with pytest.raises(IntegrityError):  # one report per interview
        async with app_db.tenant(org) as session:
            session.add(report())
    with pytest.raises(IntegrityError):  # released needs the frozen items and the approver
        async with app_db.tenant(org) as session:
            await session.execute(update(Report).values(status="released"))
    async with app_db.tenant(org) as session:
        await session.execute(
            update(Report).values(status="released", released_items={}, approved_by=user)
        )


async def test_an_export_belongs_to_an_interview_or_a_candidate_and_is_never_changed(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_hiring: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    hiring, interview, _, user = await scene(admin_engine, make_hiring, make_user, org)

    def export(**changes: Any) -> ReportExport:
        fields: dict[str, Any] = {
            "organization_id": org,
            "kind": "interview",
            "interview_id": interview,
            "requested_by": user,
            "blob_path": f"{org}/interviews/{interview}/report/interview-x.pdf",
            "bytes": 10,
            "sha256": "0" * 64,
            "document_sha256": "1" * 64,
            "renderer": "chromium",
        }
        return ReportExport(**{**fields, **changes})

    async with app_db.tenant(org) as session:
        session.add(export())
        session.add(export(kind="candidate", interview_id=None, candidate_id=hiring.candidate_id))
    for bad in (export(interview_id=None), export(kind="summary"), export(audience="public")):
        with pytest.raises(IntegrityError):
            async with app_db.tenant(org) as session:
                session.add(bad)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with app_db.tenant(org) as session:
            await session.execute(text("UPDATE report_exports SET bytes = 1"))
