"""Candidate 360 and the unified timeline over HTTP (SP-17; PRD §20, §98): the tabs' data for what
the reader may see, and one timeline across eight sources, narrowed by what they may see."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.db

SOURCES = {
    "screening",
    "interview",
    "transcript",
    "coding",
    "proctoring",
    "recording",
    "evaluation",
    "recruiter",
}


async def test_candidate_360_has_the_tabs_data_for_a_recruiter(
    signed_in: Any, make_organization: Any, make_reviewed_interview: Any
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    response = await client.get(f"/api/v1/candidates/{scene.hiring.candidate_id}/360")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Asha Rao"
    assert body["access"] == {
        "interviews": True,
        "proctoring": True,
        "recordings": True,
        "reports": True,
        "notes": True,
    }
    assert [a["job_title"] for a in body["applications"]] == ["Backend Engineer"]
    (interview,) = body["interviews"]
    assert interview["reference"] == "IV-0001" and interview["status"] == "evaluated"
    assert interview["evaluation"]["state"] == "ready"
    assert interview["evaluation"]["overall"]["value"] is not None
    assert {s["skill"] for s in interview["evaluation"]["skills"]} == {"PostgreSQL", "Python"}
    assert interview["proctoring"] == {"critical": 1, "warning": 7, "info": 1, "reviewed": 1}
    assert sorted(r["kind"] for r in interview["recordings"]) == [
        "audio",
        "camera",
        "screen",
        "third_eye",
    ]
    assert interview["code_snapshots"] == 1 and interview["candidate_report_status"] == "none"
    assert {s["skill"] for s in body["skills"]} == {"PostgreSQL", "Python"}
    assert [n["body"] for n in body["notes"]] == ["Confident on query plans."]


async def test_a_reader_without_interview_permissions_gets_no_interview_data(
    signed_in: Any, make_organization: Any, make_reviewed_interview: Any, make_user: Any
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    manager = await signed_in(org, await make_user(org, roles=["hiring_manager"]))
    body = (await manager.get(f"/api/v1/candidates/{scene.hiring.candidate_id}/360")).json()
    # A hiring manager sees interviews and proctoring (their role holds both).
    assert body["access"]["interviews"] is True and len(body["interviews"]) == 1
    stranger_org = await make_organization("Globex")
    stranger = await signed_in(stranger_org, await make_user(stranger_org, roles=["recruiter"]))
    gone = await stranger.get(f"/api/v1/candidates/{scene.hiring.candidate_id}/360")
    assert gone.status_code == 404


async def test_the_timeline_unifies_the_sources_newest_first_and_pages(
    signed_in: Any, make_organization: Any, make_reviewed_interview: Any
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    client = await signed_in(org, scene.hiring.recruiter_id)
    path = f"/api/v1/candidates/{scene.hiring.candidate_id}/timeline"
    everything = (await client.get(path, params={"limit": 200})).json()
    items = everything["items"]
    assert {item["source"] for item in items} >= SOURCES - {"screening"}
    moments = [item["at"] for item in items]
    assert moments == sorted(moments, reverse=True)
    phone = next(i for i in items if i["title"] == "Phone seen in the camera")
    assert phone["offset_ms"] == 150_000 and phone["severity"] == "CRITICAL"

    only = (await client.get(path, params=[("source", "proctoring")])).json()["items"]
    assert only and {i["source"] for i in only} == {"proctoring"}
    interview = (
        await client.get(path, params={"interview_id": str(scene.interview_id), "limit": 5})
    ).json()
    assert len(interview["items"]) == 5 and interview["next_before"] is not None
    older = (
        await client.get(
            path,
            params={
                "interview_id": str(scene.interview_id),
                "limit": 200,
                "before": interview["next_before"],
            },
        )
    ).json()
    assert older["items"], "the older page holds the rest of the interview's entries"
    assert all(i["at"] < interview["next_before"] for i in older["items"])


async def test_the_timeline_leaves_out_sources_the_reader_may_not_see(
    signed_in: Any,
    admin_engine: Any,
    make_organization: Any,
    make_reviewed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    # A custom role that can see candidates but neither interviews nor proctoring.
    from sqlalchemy import text

    from hirevion_core.ids import uuid7
    from hirevion_core.models import Role  # noqa: F401  (a custom role is made below)

    role = uuid7()
    async with admin_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO roles (id, organization_id, name, system) "
                "VALUES (:i, :o, 'Sourcer', false)"
            ),
            {"i": role, "o": org},
        )
        await conn.execute(
            text(
                "INSERT INTO role_permissions (organization_id, role_id, permission) "
                "VALUES (:o, :r, 'candidates.view')"
            ),
            {"o": org, "r": role},
        )
    user = await make_user(org, roles=[])
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO user_roles (organization_id, user_id, role_id) VALUES (:o, :u, :r)"),
            {"o": org, "u": user, "r": role},
        )
    sourcer = await signed_in(org, user)
    path = f"/api/v1/candidates/{scene.hiring.candidate_id}/timeline"
    items = (await sourcer.get(path, params={"limit": 200})).json()["items"]
    assert {i["source"] for i in items} <= {"screening", "recruiter"}
    full = (await sourcer.get(f"/api/v1/candidates/{scene.hiring.candidate_id}/360")).json()
    assert full["interviews"] == [] and full["access"]["interviews"] is False
    assert full["access"]["proctoring"] is False
