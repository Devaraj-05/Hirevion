"""Candidate 360, the internal candidate report, the review media, the pending-review queue and
the pipeline (SP-17; PRD §19, §20, §71, §72)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import NotFound
from hirevion_core.access.scope import ResourceScope
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.models import Interview, ScreeningResult
from hirevion_core.proctoring.review import review_event
from hirevion_core.reports import candidate as candidate_report
from hirevion_core.reports import review
from hirevion_core.reports.candidate360 import load_candidate_360
from hirevion_core.reports.data import load_interview_data
from hirevion_core.storage.paths import BlobPath

from .test_report_documents import full_scene

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
EVERYTHING = ResourceScope(UUID(int=0), organization_wide=True, team_ids=frozenset())


def perms(*roles: str) -> frozenset[str]:
    return frozenset(permissions_for(roles))


async def awaiting(admin_engine: AsyncEngine, scene: Any) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE applications SET stage = 'interviewed', "
                "hiring_status = 'interview_completed' WHERE id = :id"
            ),
            {"id": scene.hiring.application_id},
        )


async def test_candidate_360_loads_what_the_reader_may_see(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await full_scene(app_db, org, make_completed_interview, add_telemetry, make_user)
    candidate_id = scene.hiring.candidate_id
    async with app_db.tenant(org) as session:
        full = await load_candidate_360(session, candidate_id, EVERYTHING, perms("recruiter"))
        assert [data.interview.id for data in full.interviews] == [scene.interview_id]
        assert [note.body for note in full.notes] == ["Confident on query plans."]
        assert len(full.hiring_inputs[scene.hiring.application_id]) == 1
        # Without permission to see interviews, none load; the profile and notes still do.
        limited = await load_candidate_360(
            session, candidate_id, EVERYTHING, frozenset({"candidates.view"})
        )
        assert limited.interviews == [] and limited.exports == []
        assert limited.detail.candidate.name == "Asha Rao"
        # Someone whose scope doesn't reach the job doesn't find the candidate at all.
        nobody = ResourceScope(UUID(int=5), organization_wide=False, team_ids=frozenset())
        with pytest.raises(NotFound):
            await load_candidate_360(session, candidate_id, nobody, perms("recruiter"))


async def test_the_internal_candidate_report_has_eleven_sections(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await full_scene(app_db, org, make_completed_interview, add_telemetry, make_user)
    hiring = scene.hiring
    async with app_db.tenant(org) as session:
        session.add(
            ScreeningResult(
                organization_id=org,
                application_id=hiring.application_id,
                job_id=hiring.job_id,
                candidate_id=hiring.candidate_id,
                cache_key="k" * 8,
                score=82,
                strengths=["Strong PostgreSQL"],
                concerns=["No cloud experience"],
            )
        )
    async with app_db.tenant(org) as session:
        c360 = await load_candidate_360(
            session, hiring.candidate_id, EVERYTHING, perms("recruiter")
        )
        doc = await candidate_report.candidate_report(session, c360)
    assert [s["key"] for s in doc["sections"]] == list(candidate_report.SECTION_KEYS)
    status = {s["key"]: s["status"] for s in doc["sections"]}
    assert status.pop("coding") == "pending"
    assert set(status.values()) == {"populated"}, status
    assert doc["confidential"] is True and doc["kind"] == "candidate"
    text_of = str(doc)
    assert "Fits the platform team." in text_of and "Confident on query plans." in text_of


async def test_the_queue_lists_interviews_waiting_for_a_person_oldest_first(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene, telemetry, recruiter = await full_scene(
        app_db, org, make_completed_interview, add_telemetry, make_user
    )
    other = await make_completed_interview(org)  # not waiting: still under review
    await awaiting(admin_engine, scene)
    async with app_db.tenant(org) as session:
        waiting, total = await review.pending_reviews(session, EVERYTHING)
        assert total == 1 and [w.interview.id for w in waiting] == [scene.interview_id]
        item = waiting[0]
        assert item.evaluated and item.overall_score is not None
        assert item.unreviewed_critical == 1  # the phone event hasn't been reviewed
        assert item.candidate.name == "Asha Rao" and item.hiring_status == "interview_completed"
        assert await review.pending_count(session, EVERYTHING) == 1
        await review_event(
            session,
            Actor(recruiter, org, perms("recruiter")),
            scene.interview_id,
            telemetry.events["PHONE_DETECTED"],
            "confirmed",
            "Clearly a phone.",
        )
        again, _ = await review.pending_reviews(session, EVERYTHING)
        assert again[0].unreviewed_critical == 0
        outside = ResourceScope(UUID(int=7), organization_wide=False, team_ids=frozenset())
        assert await review.pending_reviews(session, outside) == ([], 0)
    del other


async def test_the_pipeline_has_nine_columns_with_the_moves_each_card_allows(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    await awaiting(admin_engine, scene)
    fresh = await make_hiring(org, candidate_name="Ben Cole")
    async with app_db.tenant(org) as session:
        columns = await review.pipeline(session, EVERYTHING, can_manage=True, can_decide=True)
        assert [c.status for c in columns] == [
            "under_review",
            "shortlisted",
            "interview_invited",
            "interview_started",
            "interview_completed",
            "additional_review",
            "selected",
            "rejected",
            "on_hold",
        ]
        by_status = {c.status: c for c in columns}
        done = by_status["interview_completed"]
        assert done.count == 1 and done.cards[0].candidate_name == "Asha Rao"
        assert "selected" in done.cards[0].moves and "interview_started" not in done.cards[0].moves
        waiting = by_status["under_review"]
        assert {card.candidate_id for card in waiting.cards} == {fresh.candidate_id}
        assert "selected" not in waiting.cards[0].moves  # no interview yet
        # Someone who can't manage moves nothing.
        plain = await review.pipeline(session, EVERYTHING, can_manage=False, can_decide=False)
        assert all(card.moves == [] for column in plain for card in column.cards)


class FakeSigner:
    def download_url(
        self, organization_id: UUID, path: BlobPath, expires: Any = None, filename: Any = None
    ) -> str:
        return f"https://files.test/{path}"


class FakeStorage:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs

    async def get(self, path: BlobPath) -> bytes:
        try:
            return self.blobs[path.key]
        except KeyError as error:
            raise FileNotFoundError(path.key) from error


async def test_the_review_media_carries_each_tracks_timeline_map(
    app_db: Database,
    admin_engine: AsyncEngine,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    telemetry = await add_telemetry(scene)
    map_ = {
        "track": "camera",
        "started_at": telemetry.started_at.isoformat(),
        "segments": [
            {
                "seq": 0,
                "started_at": telemetry.started_at.isoformat(),
                "duration_ms": 10_000,
                "file_offset_ms": 0,
            }
        ],
        "gaps": [],
    }
    key = f"interviews/{scene.interview_id}/camera/camera-timeline.json"
    storage = FakeStorage({key: json.dumps(map_).encode()})
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        data = await load_interview_data(session, interview, with_transcript=False)
        found = await review.review_media(session, FakeSigner(), storage, data)  # type: ignore[arg-type]
    assert [t.kind for t in found] == ["camera", "screen", "third_eye", "audio"]
    camera = found[0]
    assert (
        camera.url and camera.url.startswith("https://files.test/") and camera.container == "webm"
    )
    assert camera.timeline == map_ and camera.duration_ms == 2_400_000
    assert found[1].timeline is None  # no map stored for it: the player falls back to the anchor
    assert data.anchor == telemetry.started_at + timedelta(0)
