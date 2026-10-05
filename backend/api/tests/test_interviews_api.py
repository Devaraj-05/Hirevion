"""The question library, interview templates and interview defaults over HTTP (SP-06 Task 5)."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from hirevion_core.ai import build_ai
from hirevion_core.ai.mock import MockLLM
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import AiUnavailable, ChatMessage
from hirevion_core.db.session import Database

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def question(text: str, **overrides: Any) -> dict[str, Any]:
    return {
        "text": text,
        "skill_name": "Python",
        "topic": "Runtime",
        "difficulty": "medium",
        "type": "conceptual",
        "expected_concepts": ["reference counting", "cycle detection"],
        "rubric": [
            {"criterion": "Correctness", "weight": 70},
            {"criterion": "Depth", "weight": 30},
        ],
        "time_limit_seconds": 300,
        "follow_up_rules": [{"when": "weak", "prompt": "Can you give an example?"}],
        **overrides,
    }


@pytest.fixture
async def acme(make_organization: MakeOrganization) -> UUID:
    return await make_organization("Acme")


@pytest.fixture
async def recruiter(signed_in, acme: UUID, make_user) -> AsyncClient:
    return await signed_in(acme, await make_user(acme, roles=["recruiter"]))


@pytest.fixture
async def admin(signed_in, acme: UUID, make_user) -> AsyncClient:
    return await signed_in(acme, await make_user(acme, roles=["org_admin"]))


@pytest.fixture
async def manager(signed_in, acme: UUID, make_user) -> AsyncClient:
    return await signed_in(acme, await make_user(acme, roles=["hiring_manager"]))


async def test_questions_are_written_versioned_approved_and_archived(
    recruiter: AsyncClient,
) -> None:
    created = await recruiter.post(
        "/api/v1/questions",
        json=question("Explain how Python's garbage collector handles cycles.", status="draft"),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["status"], body["version"], body["category"]) == ("draft", 1, "technical")
    qid = body["id"]

    edited = await recruiter.put(
        f"/api/v1/questions/{qid}",
        json=question("Explain how CPython's garbage collector finds reference cycles."),
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["version"], edited.json()["status"]) == (2, "draft")
    versions = (await recruiter.get(f"/api/v1/questions/{qid}/versions")).json()
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["text"].startswith("Explain how Python's")

    drafts = (await recruiter.get("/api/v1/questions", params={"status": "draft"})).json()
    assert [item["id"] for item in drafts["items"]] == [qid]
    approved = await recruiter.post(f"/api/v1/questions/{qid}/approve")
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_at"] is not None

    found = (await recruiter.get("/api/v1/questions", params={"q": "CPython cycles"})).json()
    assert [item["id"] for item in found["items"]] == [qid]
    assert (await recruiter.post(f"/api/v1/questions/{qid}/archive")).json()["status"] == (
        "archived"
    )
    assert (await recruiter.get("/api/v1/questions")).json()["items"] == []
    refused = await recruiter.put(f"/api/v1/questions/{qid}", json=question("Something new here"))
    assert refused.status_code == 409
    assert refused.json()["code"] == "question-archived"
    restored = await recruiter.post(f"/api/v1/questions/{qid}/restore")
    assert restored.json()["status"] == "draft"


async def test_question_bodies_are_checked(recruiter: AsyncClient) -> None:
    short = await recruiter.post("/api/v1/questions", json=question("Why?"))
    assert short.status_code == 422
    assert short.json()["code"] == "text-too-short"
    rubric = await recruiter.post(
        "/api/v1/questions",
        json=question(
            "Explain the GIL and its effect on threads.",
            rubric=[{"criterion": "Correctness", "weight": 50}],
        ),
    )
    assert rubric.status_code == 422
    unknown = await recruiter.post(
        "/api/v1/questions", json=question("Explain the GIL.", type="trivia")
    )
    assert unknown.status_code == 422


async def test_drafts_are_generated_by_the_ai_for_review(
    api: FastAPI, app_db: Database, recruiter: AsyncClient
) -> None:
    ai = build_ai(AiSettings(profile="mock"), app_db)
    assert isinstance(ai.llm, MockLLM)
    sent: list[str] = []

    def script(messages: Sequence[ChatMessage]) -> Any:
        sent.append(messages[-1]["content"])
        return {
            "questions": [
                question("How would you profile a slow FastAPI endpoint?"),
                question("Walk me through a race condition you debugged.", type="scenario"),
            ]
        }

    ai.llm.scripted["questions.generate"] = script
    api.state.ai = ai
    job = (
        await recruiter.post(
            "/api/v1/jobs", json={"title": "Backend Engineer", "skills": [{"name": "Python"}]}
        )
    ).json()

    response = await recruiter.post(
        "/api/v1/questions/generate",
        json={"skills": ["Python"], "count": 2, "experience_level": "senior", "job_id": job["id"]},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert (len(result["drafts"]), result["skipped"]) == (2, 0)
    assert all(d["status"] == "draft" and d["source"] == "ai" for d in result["drafts"])
    assert result["drafts"][0]["generation"]["inputs"]["job"] == job["id"]
    assert "Backend Engineer" in sent[0]

    ai.llm.failures.append(AiUnavailable("down"))
    down = await recruiter.post("/api/v1/questions/generate", json={"skills": ["Python"]})
    assert down.status_code == 503
    assert down.json()["code"] == "ai-unavailable"


async def test_generation_needs_the_ai(api: FastAPI, recruiter: AsyncClient) -> None:
    api.state.ai = None
    response = await recruiter.post("/api/v1/questions/generate", json={"skills": ["Python"]})
    assert response.status_code == 503
    assert response.json()["code"] == "ai-unavailable"


async def test_templates_version_on_every_edit_and_preview_the_matrix(
    recruiter: AsyncClient,
) -> None:
    qid = (
        await recruiter.post(
            "/api/v1/questions", json=question("Explain how asyncio schedules coroutines.")
        )
    ).json()["id"]
    created = await recruiter.post(
        "/api/v1/interview-templates",
        json={
            "name": "Backend screen",
            "skills": [{"name": "Python", "weight": 60}, {"name": "SQL", "weight": 40}],
            "question_count": 5,
            "questions": [{"question_id": qid, "version": 1}],
        },
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert (template["version"], template["duration_minutes"]) == (1, 45)
    assert template["current"]["proctoring_level"] == "standard"
    tid = template["id"]

    edited = await recruiter.patch(
        f"/api/v1/interview-templates/{tid}",
        json={"duration_minutes": 60, "proctoring_level": "strict", "third_eye": "required"},
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["version"], edited.json()["duration_minutes"]) == (2, 60)
    versions = (await recruiter.get(f"/api/v1/interview-templates/{tid}/versions")).json()
    assert [(v["version"], v["duration_minutes"]) for v in versions] == [(1, 45), (2, 60)]
    assert versions[1]["questions"] == [{"question_id": qid, "version": 1}]

    matrix = (await recruiter.get(f"/api/v1/interview-templates/{tid}/skill-matrix")).json()
    assert [(row["skill"], row["questions"]) for row in matrix] == [("Python", 3), ("SQL", 2)]
    assert matrix[0]["available"]["medium"] == 1
    preview = await recruiter.post(
        "/api/v1/interview-templates/skill-matrix",
        json={
            "question_count": 4,
            "skills": [{"name": "Go", "weight": 100}],
            "difficulty": {"easy": 50, "medium": 50, "hard": 0},
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()[0]["by_difficulty"] == {"easy": 2, "medium": 2, "hard": 0}
    assert preview.json()[0]["gaps"] == {"easy": 2, "medium": 2}

    listed = (await recruiter.get("/api/v1/interview-templates", params={"q": "backend"})).json()
    assert [item["id"] for item in listed["items"]] == [tid]
    taken = await recruiter.post(
        "/api/v1/interview-templates",
        json={"name": "backend SCREEN", "skills": [{"name": "Go", "weight": 100}]},
    )
    assert taken.status_code == 409
    assert taken.json()["code"] == "name-taken"

    archived = await recruiter.post(f"/api/v1/interview-templates/{tid}/archive")
    assert archived.json()["status"] == "archived"
    assert (await recruiter.get("/api/v1/interview-templates")).json()["items"] == []
    restored = await recruiter.post(f"/api/v1/interview-templates/{tid}/restore")
    assert restored.json()["status"] == "active"


async def test_templates_refuse_drafts_and_bad_mixes(recruiter: AsyncClient) -> None:
    draft = (
        await recruiter.post(
            "/api/v1/questions",
            json=question("Explain Python's descriptor protocol.", status="draft"),
        )
    ).json()["id"]
    pinned = await recruiter.post(
        "/api/v1/interview-templates",
        json={
            "name": "Pins a draft",
            "skills": [{"name": "Python", "weight": 100}],
            "questions": [{"question_id": draft, "version": 1}],
        },
    )
    assert pinned.status_code == 422
    assert pinned.json()["code"] == "question-not-approved"
    weights = await recruiter.post(
        "/api/v1/interview-templates",
        json={"name": "Bad weights", "skills": [{"name": "Python", "weight": 60}]},
    )
    assert weights.status_code == 422


async def test_interview_defaults_are_read_by_template_builders_and_set_by_admins(
    admin: AsyncClient, recruiter: AsyncClient, manager: AsyncClient
) -> None:
    shown = (await recruiter.get("/api/v1/interview-defaults")).json()
    assert (shown["duration_minutes"], shown["proctoring_level"]) == (45, "standard")
    assert shown["proctoring_presets"]["off"] == []
    assert (await recruiter.put("/api/v1/interview-defaults", json={})).status_code == 403
    assert (await manager.get("/api/v1/interview-defaults")).status_code == 403

    saved = await admin.put(
        "/api/v1/interview-defaults", json={"duration_minutes": 30, "third_eye": "required"}
    )
    assert saved.status_code == 200, saved.text
    assert (saved.json()["duration_minutes"], saved.json()["question_count"]) == (30, 10)
    template = (
        await recruiter.post(
            "/api/v1/interview-templates",
            json={"name": "Quick screen", "skills": [{"name": "Python", "weight": 100}]},
        )
    ).json()
    assert (template["duration_minutes"], template["third_eye"]) == (30, "required")


async def test_other_organisations_cannot_see_the_library(
    recruiter: AsyncClient, signed_in, make_organization: MakeOrganization, make_user
) -> None:
    qid = (
        await recruiter.post("/api/v1/questions", json=question("Explain Python's import system."))
    ).json()["id"]
    other = await make_organization("Globex")
    outsider = await signed_in(other, await make_user(other, roles=["recruiter"]))
    assert (await outsider.get(f"/api/v1/questions/{qid}")).status_code == 404
    assert (await outsider.get("/api/v1/questions")).json()["items"] == []
