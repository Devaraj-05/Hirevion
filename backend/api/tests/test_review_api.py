"""The review workspace and the hiring workflow over HTTP (SP-17; PRD §71, §72, §97): the player's
media (audited as `recording.viewed`), notes, score changes with a reason (`score.modified`),
Hiring Manager input, the status and the final decision, the pending-review queue and the
pipeline."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings
from hirevion_core.db.session import Database
from hirevion_core.identity.settings import IdentitySettings
from hirevion_core.storage.service import StorageService, ensure_storage, load_storage_settings

pytestmark = pytest.mark.db

ORIGIN = "https://app.hirevion.localhost"
IDENTITY = IdentitySettings(hibp_enabled=False, web_origin=ORIGIN)


@pytest.fixture
async def storage() -> AsyncIterator[StorageService]:
    settings = load_storage_settings()
    direct = settings.model_copy(update={"storage_public_endpoint": settings.internal_endpoint})
    await ensure_storage(direct, [ORIGIN])
    service = StorageService(direct)
    yield service
    await service.aclose()


@pytest.fixture
def api(app_db: Database, valkey: Redis, storage: StorageService) -> FastAPI:
    return create_app(
        ApiSettings(allowed_origins=ORIGIN, run_workers=False, ip_rate_limit=100_000),
        db=app_db,
        redis=valkey,
        identity=IDENTITY,
        storage=storage,
    )


async def audited(admin_engine: AsyncEngine, org: UUID, action: str) -> list[dict[str, Any]]:
    async with admin_engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT details, actor_id FROM audit_logs WHERE organization_id = :o "
                "AND action = :a ORDER BY seq"
            ),
            {"o": org, "a": action},
        )
        return [{**dict(r.details), "_actor": r.actor_id} for r in rows]


def url(scene: Any, tail: str) -> str:
    return f"/api/v1/interviews/{scene.interview_id}{tail}"


async def awaiting_decision(admin_engine: AsyncEngine, scene: Any) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE applications SET stage = 'interviewed', "
                "hiring_status = 'interview_completed' WHERE id = :id"
            ),
            {"id": scene.hiring.application_id},
        )


async def test_the_review_media_lists_every_track_and_playing_it_is_audited(
    signed_in: Any,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, telemetry, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    response = await client.get(url(scene, "/review/media"))
    assert response.status_code == 200
    body = response.json()
    assert [t["kind"] for t in body["tracks"]] == ["camera", "screen", "third_eye", "audio"]
    assert body["anchor"].startswith(telemetry.started_at.strftime("%Y-%m-%dT%H:%M:%S"))
    camera = body["tracks"][0]
    assert camera["status"] == "assembled" and camera["url"] and camera["container"] == "webm"
    assert camera["duration_ms"] == 2_400_000 and camera["label"] == "Camera"
    entries = await audited(admin_engine, org, "recording.viewed")
    assert len(entries) == 1 and entries[0]["via"] == "review"
    assert entries[0]["tracks"] == ["camera", "mic", "screen-1", "third-eye-1"] or sorted(
        entries[0]["tracks"]
    ) == ["camera", "mic", "screen-1", "third-eye-1"]
    # Every play is audited: the log shows each viewing.
    await client.get(url(scene, "/review/media"))
    assert len(await audited(admin_engine, org, "recording.viewed")) == 2


async def test_notes_can_be_added_at_a_moment_and_are_listed(
    signed_in: Any,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_reviewed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    added = await client.post(
        url(scene, "/notes"), json={"body": "Hesitated here.", "at_ms": 90_000}
    )
    assert added.status_code == 201
    assert added.json()["at_ms"] == 90_000 and added.json()["interview_id"] == str(
        scene.interview_id
    )
    listed = (await client.get(url(scene, "/notes"))).json()["items"]
    assert [n["body"] for n in listed] == ["Hesitated here.", "Confident on query plans."]
    assert (await client.post(url(scene, "/notes"), json={"body": "  "})).status_code == 422
    assert (
        await client.post(url(scene, "/notes"), json={"body": "x", "at_ms": -1})
    ).status_code == 422
    general = await client.post(
        f"/api/v1/candidates/{scene.hiring.candidate_id}/notes", json={"body": "Referred by Priya."}
    )
    assert general.status_code == 201 and general.json()["interview_id"] is None
    everything = (await client.get(f"/api/v1/candidates/{scene.hiring.candidate_id}/notes")).json()
    assert len(everything["items"]) == 3
    assert (
        len(await audited(admin_engine, org, "candidate.note_added")) == 3
    )  # one came with the scene, two were added here
    stranger_org = await make_organization("Globex")
    stranger = await signed_in(stranger_org, await make_user(stranger_org, roles=["recruiter"]))
    assert (await stranger.get(url(scene, "/notes"))).status_code == 404
    assert (
        await stranger.get(f"/api/v1/candidates/{scene.hiring.candidate_id}/notes")
    ).status_code == 404


async def test_a_score_change_keeps_the_ai_score_and_is_audited(
    signed_in: Any,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_reviewed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    before = (await client.get(url(scene, "/scores"))).json()
    ai_overall = before["overall"]["ai"]
    assert before["overall"]["value"] == ai_overall and before["overall"]["change"] is None
    assert before["communication"]["change"]["reason"] == "Spoke clearly but slowly."

    changed = await client.post(
        url(scene, "/score-changes"),
        json={"scope": "skill", "target": "Python", "new_score": 7.5, "reason": "Saw the code."},
    )
    assert changed.status_code == 201, changed.text
    python = changed.json()["skills"]["Python"]
    assert python["value"] == 7.5 and python["ai"] is not None and python["ai"] != 7.5
    assert python["change"]["reason"] == "Saw the code." and python["change"]["changed_by_name"]
    assert changed.json()["overall"]["ai"] == ai_overall  # nothing else moved
    entries = await audited(admin_engine, org, "score.modified")
    assert [e["scope"] for e in entries] == ["communication", "skill"]
    assert entries[1]["target"] == "Python" and entries[1]["new"] == 7.5
    assert entries[1]["_actor"] == str(scene.hiring.recruiter_id)

    bad = await client.post(
        url(scene, "/score-changes"),
        json={"scope": "skill", "target": "Rust", "new_score": 5, "reason": "x"},
    )
    assert bad.status_code == 422 and bad.json()["code"] == "unknown-target"
    no_reason = await client.post(
        url(scene, "/score-changes"), json={"scope": "overall", "new_score": 5, "reason": ""}
    )
    assert no_reason.status_code == 422
    # Reading is open to reviewers; changing a score needs the permission.
    manager = await signed_in(org, await make_user(org, roles=["hiring_manager"]))
    assert (await manager.get(url(scene, "/scores"))).status_code == 200
    forbidden = await manager.post(
        url(scene, "/score-changes"), json={"scope": "overall", "new_score": 5, "reason": "x"}
    )
    assert forbidden.status_code == 403


async def test_hiring_input_informs_the_decision_and_a_recruiter_makes_it(
    signed_in: Any,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_reviewed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    await awaiting_decision(admin_engine, scene)
    application = scene.hiring.application_id
    base = f"/api/v1/applications/{application}"
    manager = await signed_in(org, await make_user(org, roles=["hiring_manager"]))
    recruiter = await signed_in(org, scene.hiring.recruiter_id)

    # The Hiring Manager recommends; that moves nothing.
    given = await manager.post(
        f"{base}/hiring-inputs",
        json={"recommendation": "strong_hire", "ratings": {"technical": 5}, "rationale": "Great."},
    )
    assert given.status_code == 201 and given.json()["recommendation"] == "strong_hire"
    state = (await recruiter.get(f"{base}/hiring")).json()
    assert state["status"] == "interview_completed" and state["has_interview"] is True
    assert {i["author_name"] for i in state["inputs"]} == {"Test User"}
    assert state["allowed"] == [
        "under_review",
        "shortlisted",
        "additional_review",
        "selected",
        "rejected",
        "on_hold",
    ]
    # A recruiter can't give hiring input; a hiring manager can't move the status.
    assert (
        await recruiter.post(
            f"{base}/hiring-inputs", json={"recommendation": "hire", "rationale": "x"}
        )
    ).status_code == 403
    assert (
        await manager.post(f"{base}/hiring-status", json={"status": "selected", "reason": "x"})
    ).status_code == 403

    # The system-only statuses can't be chosen and a decision says why.
    system = await recruiter.post(f"{base}/hiring-status", json={"status": "interview_started"})
    assert system.status_code == 409 and system.json()["code"] == "system-status"
    silent = await recruiter.post(f"{base}/hiring-status", json={"status": "selected"})
    assert silent.status_code == 422 and silent.json()["code"] == "reason-required"

    chosen = await recruiter.post(
        f"{base}/hiring-status",
        json={"status": "selected", "reason": "The strongest candidate for the role."},
    )
    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert body["status"] == "selected" and body["decision"]["decision"] is True
    assert body["decision"]["reason"].startswith("The strongest") and body["decision"]["actor_name"]
    assert body["history"][0]["to_status"] == "selected" and body["allowed"][0] == "under_review"
    decided = await audited(admin_engine, org, "hiring.decided")
    assert decided[-1]["decision"] == "selected" and decided[-1]["from"] == "interview_completed"
    assert decided[-1]["_actor"] == str(scene.hiring.recruiter_id)
    assert (
        len(await audited(admin_engine, org, "hiring.input_added")) == 2
    )  # one came with the scene


async def test_the_pending_queue_and_the_pipeline_follow_the_status(
    signed_in: Any,
    admin_engine: AsyncEngine,
    make_organization: Any,
    make_reviewed_interview: Any,
    make_user: Any,
    make_hiring: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    waiting_other = await make_hiring(org, candidate_name="Ben Cole")
    await awaiting_decision(admin_engine, scene)
    recruiter = await signed_in(org, scene.hiring.recruiter_id)

    queue = (await recruiter.get("/api/v1/reviews/pending")).json()
    assert queue["total"] == 1
    item = queue["items"][0]
    assert item["interview_id"] == str(scene.interview_id) and item["candidate_name"] == "Asha Rao"
    assert item["evaluated"] is True and item["overall_score"] is not None
    assert item["unreviewed_critical"] == 1 and item["reference"] == "IV-0001"
    dashboard = (await recruiter.get("/api/v1/dashboard")).json()
    assert dashboard["pending_reviews"] == 1

    # An interviewer sees only what they review.
    interviewer = await make_user(org, roles=["interviewer"])
    other = await signed_in(org, interviewer)
    assert (await other.get("/api/v1/reviews/pending")).json()["total"] == 0

    board = (await recruiter.get("/api/v1/pipeline")).json()
    assert [c["status"] for c in board["columns"]][:5] == [
        "under_review",
        "shortlisted",
        "interview_invited",
        "interview_started",
        "interview_completed",
    ]
    done = next(c for c in board["columns"] if c["status"] == "interview_completed")
    assert done["count"] == 1 and "selected" in done["cards"][0]["moves"]
    # Moving a card is the status change: the card lands in its new column.
    card = next(
        c
        for col in board["columns"]
        for c in col["cards"]
        if c["candidate_id"] == str(waiting_other.candidate_id)
    )
    moved = await recruiter.post(
        f"/api/v1/applications/{card['application_id']}/hiring-status",
        json={"status": "on_hold", "reason": "Waiting on the budget"},
    )
    assert moved.status_code == 200 and moved.json()["status"] == "on_hold"
    after = (await recruiter.get("/api/v1/pipeline")).json()
    held = next(c for c in after["columns"] if c["status"] == "on_hold")
    assert [c["candidate_name"] for c in held["cards"]] == ["Ben Cole"]
    # Nobody who can't see candidates sees the board.
    assert (await other.get("/api/v1/pipeline")).status_code == 403
