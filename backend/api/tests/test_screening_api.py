"""Screening configuration, results, actions and export over HTTP (SP-05 Task 5)."""

import csv
from collections.abc import Awaitable, Callable, Sequence
from io import BytesIO, StringIO
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.ai import build_ai
from hirevion_core.ai.mock import MockLLM
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import ChatMessage
from hirevion_core.candidates import profiles
from hirevion_core.db.session import Database
from hirevion_core.documents.resume import ResumeResult
from hirevion_core.models import Application, Document
from hirevion_core.screening.runner import handle_screening_event

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
PEOPLE = (("=Asha Rao", ["Python"], 90), ("Ravi Kumar", [], 20))


def assessment(messages: Sequence[ChatMessage]) -> Any:
    score = 90 if "file 0" in messages[-1]["content"] else 20
    factor = {"score": score, "evidence": []}
    return {
        "roles": factor,
        "projects": factor,
        "domain": factor,
        "education": {"score": 100, "evidence": []},
        "location": {"score": 100, "evidence": []},
        "strengths": ["Good fit"] if score > 50 else [],
        "concerns": [],
        "missing_requirements": [],
    }


@pytest.fixture
async def acme(make_organization: MakeOrganization) -> UUID:
    return await make_organization("Acme")


@pytest.fixture
async def recruiter(signed_in, acme: UUID, make_user) -> AsyncClient:
    return await signed_in(acme, await make_user(acme, roles=["recruiter"]))


async def job_with_candidates(client: AsyncClient, app_db: Database, acme: UUID) -> str:
    job = (
        await client.post(
            "/api/v1/jobs", json={"title": "Backend Engineer", "skills": [{"name": "Python"}]}
        )
    ).json()
    async with app_db.tenant(acme) as session:
        for index, (name, skills, _) in enumerate(PEOPLE):
            document = Document(
                organization_id=acme,
                kind="resume",
                job_id=UUID(job["id"]),
                sha256=f"{index:064d}",
                text=f"Candidate file {index}\nSkills\n{', '.join(skills)}",
                status="parsed",
            )
            session.add(document)
            await session.flush()
            profile = {
                "name": {"value": name, "quote": name},
                "email": {"value": f"person{index}@x.test", "quote": "x"},
                "skills": [{"name": skill, "quote": skill} for skill in skills],
            }
            await profiles.build(
                session, document, ResumeResult(profile, 0, "fake"), flags={}, embedding=None
            )
    return str(job["id"])


async def screen(client: AsyncClient, app_db: Database, acme: UUID, job_id: str) -> None:
    answer = await client.post(f"/api/v1/jobs/{job_id}/screen", json={})
    assert (answer.status_code, answer.json()["queued"]) == (202, 2)
    ai = build_ai(AiSettings(profile="mock"), app_db)
    assert isinstance(ai.llm, MockLLM)
    ai.llm.scripted["screening.assess"] = assessment
    async with app_db.tenant(acme) as session:
        ids = (await session.scalars(select(Application.id))).all()
    for application_id in ids:
        await handle_screening_event(
            app_db, ai, acme, {"action": "screen", "application_id": str(application_id)}
        )


async def test_configuration_inherits_and_validates(
    recruiter: AsyncClient, signed_in, acme: UUID, make_user
) -> None:
    job_id = (await recruiter.post("/api/v1/jobs", json={"title": "Engineer"})).json()["id"]
    inherited = (await recruiter.get(f"/api/v1/jobs/{job_id}/screening-config")).json()
    assert (inherited["inherited"], inherited["weights"]["required_skills"]) == (True, 35)

    bad = await recruiter.put(
        f"/api/v1/jobs/{job_id}/screening-config",
        json={"weights": {**inherited["weights"], "experience": 50}},
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "weights-total")
    # Blind screening is on by default and only an organisation administrator turns it off.
    locked = await recruiter.put(f"/api/v1/jobs/{job_id}/screening-config", json={"blind": False})
    assert (locked.status_code, locked.json()["code"]) == (403, "blind-screening-locked")
    kept = await recruiter.put(
        f"/api/v1/jobs/{job_id}/screening-config", json={"knockouts": {"min_experience": False}}
    )
    assert (kept.json()["inherited"], kept.json()["blind"]) == (False, True)
    admin = await signed_in(acme, await make_user(acme, roles=["org_admin"]))
    own = await admin.put(f"/api/v1/jobs/{job_id}/screening-config", json={"blind": False})
    assert (own.json()["inherited"], own.json()["blind"]) == (False, False)
    reset = await recruiter.delete(f"/api/v1/jobs/{job_id}/screening-config")
    assert reset.json()["inherited"] is True

    default = await admin.put("/api/v1/screening-config", json={"blind": False})
    assert (default.status_code, default.json()["source"]) == (200, "organization")
    assert (await recruiter.get(f"/api/v1/jobs/{job_id}/screening-config")).json()["blind"] is False


async def test_results_are_ranked_and_explained(
    recruiter: AsyncClient, app_db: Database, acme: UUID
) -> None:
    job_id = await job_with_candidates(recruiter, app_db, acme)
    await screen(recruiter, app_db, acme, job_id)

    summary = (await recruiter.get(f"/api/v1/jobs/{job_id}/screening-summary")).json()
    assert (summary["applications"], summary["screened"], summary["waiting"]) == (2, 2, 0)

    results = (await recruiter.get(f"/api/v1/jobs/{job_id}/screening-results")).json()
    assert [(r["rank"], r["candidate"]["name"], r["stage"]) for r in results["items"]] == [
        (1, "=Asha Rao", "ranked"),
        (2, "Ravi Kumar", "ranked"),
    ]
    top = results["items"][0]
    assert top["skill_match"]["matched_required"] == ["Python"]
    detail = (await recruiter.get(f"/api/v1/applications/{top['application_id']}/screening")).json()
    assert detail["result"]["factors"]["required_skills"]["evidence"] == ["Python"]
    assert detail["result"]["strengths"] == ["Good fit"]
    assert [h["to_stage"] for h in detail["history"]] == ["screened", "ranked"]


async def test_actions_single_bulk_and_the_prd_endpoints(
    recruiter: AsyncClient, app_db: Database, acme: UUID
) -> None:
    job_id = await job_with_candidates(recruiter, app_db, acme)
    await screen(recruiter, app_db, acme, job_id)
    items = (await recruiter.get(f"/api/v1/jobs/{job_id}/screening-results")).json()["items"]
    top, last = items[0], items[1]

    shortlisted = await recruiter.post(
        f"/api/v1/candidates/{top['candidate']['id']}/shortlist", json={"job_id": job_id}
    )
    assert (shortlisted.status_code, shortlisted.json()["stage"]) == (200, "shortlisted")
    refused = await recruiter.post(
        f"/api/v1/candidates/{last['candidate']['id']}/reject", json={"job_id": job_id}
    )
    assert (refused.status_code, refused.json()["code"]) == (422, "reason-required")

    bulk = await recruiter.post(
        f"/api/v1/jobs/{job_id}/applications/actions",
        json={
            "application_ids": [top["application_id"], last["application_id"]],
            "action": "hold",
        },
    )
    assert [a["stage"] for a in bulk.json()["applications"]] == ["on_hold", "on_hold"]

    by_stage = (
        await recruiter.get("/api/v1/candidates", params={"stage_group": "screening"})
    ).json()
    assert len(by_stage["items"]) == 2


async def test_export_needs_a_recent_password_and_neutralises_formulas(
    signed_in, acme: UUID, make_user, app_db: Database
) -> None:
    user = await make_user(acme, roles=["recruiter"])
    fresh = await signed_in(acme, user)
    job_id = await job_with_candidates(fresh, app_db, acme)
    await screen(fresh, app_db, acme, job_id)

    stale = await signed_in(acme, user, stepped_up=False)
    refused = await stale.get(f"/api/v1/jobs/{job_id}/screening-results/export")
    assert (refused.status_code, refused.json()["code"]) == (403, "step-up-required")

    as_csv = await fresh.get(f"/api/v1/jobs/{job_id}/screening-results/export")
    assert as_csv.headers["content-type"].startswith("text/csv")
    assert as_csv.content.startswith(b"\xef\xbb\xbf")  # a BOM, so Excel reads UTF-8
    rows = list(csv.reader(StringIO(as_csv.text.lstrip("\ufeff"))))
    assert rows[0][:3] == ["Rank", "Candidate", "Match score"]
    assert rows[1][1] == "'=Asha Rao"  # a leading = would run as a formula in a spreadsheet

    as_xlsx = await fresh.get(
        f"/api/v1/jobs/{job_id}/screening-results/export", params={"format": "xlsx"}
    )
    sheet = load_workbook(BytesIO(as_xlsx.content)).active
    assert sheet is not None
    # Text typed as text (no apostrophe to see, no formula to run); numbers stay numbers.
    assert (sheet["B2"].value, sheet["B2"].data_type) == ("=Asha Rao", "s")
    assert isinstance(sheet["A2"].value, int) and isinstance(sheet["C2"].value, int)


async def test_a_job_or_application_out_of_reach_does_not_exist(
    recruiter: AsyncClient,
    signed_in,
    acme: UUID,
    make_user,
    app_db: Database,
    admin_engine: AsyncEngine,
) -> None:
    job_id = await job_with_candidates(recruiter, app_db, acme)
    await screen(recruiter, app_db, acme, job_id)
    application = (await recruiter.get(f"/api/v1/jobs/{job_id}/screening-results")).json()["items"][
        0
    ]["application_id"]
    outsider_id = await make_user(acme, roles=["recruiter"])
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET access_scope = 'teams' WHERE id = :id"), {"id": outsider_id}
        )
    outsider = await signed_in(acme, outsider_id)
    unknown = await outsider.get(f"/api/v1/applications/{UUID(int=3)}/screening")
    hidden = await outsider.get(f"/api/v1/applications/{application}/screening")
    assert (hidden.status_code, hidden.json()["code"]) == (404, "application-not-found")
    assert hidden.json()["code"] == unknown.json()["code"]  # the same answer as for no such id
