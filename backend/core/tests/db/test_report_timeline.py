"""The unified timeline (SP-17; PRD §98): eight sources in one order, with each interview entry's
offset from the interview's clock, and only the sources the reader may see."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from hirevion_core.access.actor import Actor
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.models import Application, Interview, ScreeningResult
from hirevion_core.reports.data import load_interview_data
from hirevion_core.reports.timeline import (
    SOURCES,
    allowed_sources,
    candidate_entries,
    interview_entries,
)

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


async def screened(
    app_db: Database, org: UUID, application_id: UUID, job_id: UUID, candidate_id: UUID
) -> None:
    async with app_db.tenant(org) as session:
        session.add(
            ScreeningResult(
                organization_id=org,
                application_id=application_id,
                job_id=job_id,
                candidate_id=candidate_id,
                cache_key="k" * 8,
                score=82,
            )
        )


async def test_the_timeline_unifies_the_eight_sources_in_order(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, recruiter = await make_reviewed_interview(org)
    hiring = scene.hiring
    await screened(app_db, org, hiring.application_id, hiring.job_id, hiring.candidate_id)
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        application = await session.get_one(Application, interview.application_id)
        # A recruiter's stage change, and a note on the candidate (not on an interview).
        from hirevion_core.hiring.notes import add_note
        from hirevion_core.screening.engine import record_stage

        await record_stage(
            session, application, "shortlisted", "shortlist", actor_id=recruiter, reason="Strong"
        )
        await add_note(
            session,
            Actor(recruiter, org, frozenset(permissions_for(["recruiter"]))),
            candidate_id=hiring.candidate_id,
            body="Referred by Priya.",
        )
        data = await load_interview_data(session, interview, with_transcript=False)
        entries = await candidate_entries(
            session, hiring.candidate_id, [application.id], [data], SOURCES
        )
    assert {entry.source for entry in entries} == set(SOURCES)
    moments = [entry.at for entry in entries]
    assert moments == sorted(moments)
    by_title = {entry.title: entry for entry in entries}
    # Interview entries carry the offset from the interview's own clock.
    phone = by_title["Phone seen in the camera"]
    assert phone.source == "proctoring" and phone.severity == "CRITICAL"
    assert phone.offset_ms == 150_000 and phone.interview_id == scene.interview_id
    assert by_title["Screened for Backend Engineer"].source == "screening"
    assert by_title["Screened for Backend Engineer"].interview_id is None
    assert by_title["Question 2 (PostgreSQL)"].source == "transcript"
    assert by_title["Code saved for question 4"].source == "coding"
    assert by_title["Camera recording ready"].source == "recording"
    assert by_title["Evaluation completed"].source == "evaluation"
    assert by_title["Shortlisted: Backend Engineer"].actor is not None
    assert by_title["Note added"].source == "recruiter"
    assert by_title["Proctor event reviewed: Looked away from the screen"].actor is not None


async def test_a_reader_sees_only_the_sources_they_may(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        application_id = (
            await session.scalars(
                select(Application.id).where(Application.id == interview.application_id)
            )
        ).one()
        data = await load_interview_data(session, interview, with_transcript=False)
        entries = await candidate_entries(
            session,
            scene.hiring.candidate_id,
            [application_id],
            [data],
            {"interview", "evaluation"},
            min_severity="CRITICAL",
        )
    assert {entry.source for entry in entries} <= {"interview", "evaluation"}
    assert entries  # the interview's own history is there
    only_serious = await _severities(app_db, org, scene, interview.id)
    assert only_serious == {"CRITICAL"}


async def _severities(app_db: Database, org: UUID, scene: Any, interview_id: UUID) -> set[str]:
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, interview_id)
        data = await load_interview_data(session, interview, with_transcript=False)
        entries = await candidate_entries(
            session,
            scene.hiring.candidate_id,
            [],
            [data],
            {"proctoring"},
            min_severity="CRITICAL",
        )
    return {entry.severity for entry in entries if entry.severity}


async def test_each_event_is_listed_once_and_only_moments_inside_the_interview_have_an_offset(
    app_db: Database,
    make_organization: MakeOrganization,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        data = await load_interview_data(session, interview, with_transcript=False)
        entries = await candidate_entries(
            session, scene.hiring.candidate_id, [interview.application_id], [data], SOURCES
        )
    # The Hiring Manager's input belongs to the application, so the candidate's timeline has it
    # once, however many interviews there are.
    assert len([entry for entry in entries if entry.kind == "hiring_input"]) == 1
    # A note says which moment of the interview it is about; what was written afterwards (the
    # evaluation, a changed score) is not inside the interview.
    note = next(entry for entry in entries if entry.kind == "note")
    assert note.offset_ms == 62_000
    for kind in ("evaluated", "score_changed", "proctor_review"):
        assert next(entry for entry in entries if entry.kind == kind).offset_ms is None, kind
    assert next(entry for entry in entries if entry.kind == "phone_detected").offset_ms == 150_000


async def test_a_reader_without_proctoring_or_the_files_people_side_sees_neither(
    app_db: Database,
    make_organization: MakeOrganization,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    interviewer = allowed_sources(permissions_for(["interviewer"]))
    assert "proctoring" not in interviewer and "recruiter" not in interviewer
    assert "transcript" in interviewer and "evaluation" in interviewer
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        data = await load_interview_data(session, interview, with_transcript=False)
        entries = interview_entries(data, interviewer)
        # A review of a proctoring event shows what the event was: it follows proctoring.
        only_recruiter = interview_entries(data, {"recruiter"})
        no_proctoring = interview_entries(data, {"recruiter", "interview"})
    assert {entry.source for entry in entries} <= interviewer
    assert not [entry for entry in no_proctoring if entry.kind == "proctor_review"]
    assert [entry for entry in only_recruiter if entry.kind == "note"]
