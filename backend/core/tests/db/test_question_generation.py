"""AI question drafts (SP-06 Task 4): inputs, de-duplication and drafts only."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Invalid
from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.mock import MockLLM
from hirevion_core.ai.settings import AiSettings
from hirevion_core.ai.types import ChatMessage
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.interviews import generation, questions
from hirevion_core.interviews.generation import GenerationRequest
from hirevion_core.interviews.questions import QuestionFields
from hirevion_core.jobs import jobs
from hirevion_core.jobs.jobs import JobChanges, SkillInput
from hirevion_core.models import Candidate, Question

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
EXISTING = "Explain how Python's garbage collector handles reference cycles."


def question(text: str, **overrides: Any) -> dict[str, Any]:
    return {
        "text": text,
        "skill_name": "Python",
        "topic": "Runtime",
        "difficulty": "medium",
        "type": "conceptual",
        "expected_concepts": ["a", "b"],
        "rubric": [
            {"criterion": "Correctness", "weight": 70},
            {"criterion": "Depth", "weight": 30},
        ],
        "time_limit_seconds": 300,
        "follow_up_rules": [{"when": "weak", "prompt": "Can you give an example?"}],
        **overrides,
    }


class Script:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def __call__(self, messages: Sequence[ChatMessage]) -> Any:
        self.sent.append(messages[-1]["content"])
        return {
            "questions": [
                question("How would you profile a slow FastAPI endpoint in production?"),
                question("explain how python's garbage-collector handles reference cycles"),
                question(
                    "Tell me about the payments gateway you built at Acme Payments.",
                    type="resume_based",
                ),
                question("Why?", skill_name="Python"),  # too short: the library refuses it
            ]
        }


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["recruiter"])
    return Actor(user, organization, frozenset(permissions_for(["recruiter"])))


@pytest.fixture
def ai(app_db: Database) -> AiServices:
    return build_ai(AiSettings(profile="mock"), app_db)


async def test_drafts_come_from_the_inputs_without_duplicates_or_personal_details(
    app_db: Database, acme: Actor, ai: AiServices
) -> None:
    script = Script()
    assert isinstance(ai.llm, MockLLM)
    ai.llm.scripted["questions.generate"] = script
    async with app_db.tenant(acme.organization_id) as session:
        await questions.create_question(
            session,
            acme,
            QuestionFields(
                text=EXISTING, skill_name="Python", difficulty="medium", type="conceptual"
            ),
        )
        job = await jobs.create_job(
            session,
            acme,
            JobChanges(title="Backend Engineer", skills=[SkillInput("Python")]),
        )
        candidate = Candidate(
            organization_id=acme.organization_id,
            name="Asha Rao",
            email="asha@x.test",
            profile={
                "name": {"value": "Asha Rao"},
                "email": {"value": "asha@x.test"},
                "positions": [{"title": "Engineer", "company": "Acme Payments", "start": "2020"}],
                "projects": [{"name": "Payments gateway", "description": "UPI transfers"}],
            },
        )
        session.add(candidate)
        await session.flush()
        request = GenerationRequest(
            skills=["Python"], count=4, job_id=job.id, candidate_id=candidate.id
        )
        message, existing = await generation.gather(session, request)

    generated, model = await generation.ask(
        ai.llm, acme.organization_id, message, refs=generation.refs_of(request)
    )
    async with app_db.tenant(acme.organization_id) as session:
        result = await generation.save_drafts(
            session, acme, generated, existing, model=model, refs=generation.refs_of(request)
        )
        assert [d.version.text[:20] for d in result.drafts] == [
            "How would you profil",
            "Tell me about the pa",
        ]
        assert result.skipped == 2
        assert all(
            d.question.status == "draft" and d.question.source == "ai" for d in result.drafts
        )
        assert result.drafts[0].version.generation["inputs"]["job"] == str(job.id)
        statuses = (await session.scalars(select(Question.status))).all()
        assert sorted(statuses) == ["approved", "draft", "draft"]

    sent = script.sent[0]
    assert "<job>" in sent and "Backend Engineer" in sent
    assert "Acme Payments" in sent and "Payments gateway" in sent
    assert "Asha" not in sent and "asha@x.test" not in sent
    assert EXISTING[:40] in sent


async def test_requests_are_checked(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        for request, code in (
            (GenerationRequest(skills=[]), "skills-required"),
            (GenerationRequest(skills=["Go"], count=11), "invalid-count"),
            (GenerationRequest(skills=["Go"], experience_level="wizard"), "invalid-level"),
        ):
            with pytest.raises(Invalid) as refusal:
                await generation.gather(session, request)
            assert refusal.value.code == code
