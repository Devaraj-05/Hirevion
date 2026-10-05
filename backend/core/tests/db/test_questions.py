"""The question library: versions, approval, archiving and filters (SP-06 Task 2)."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import select

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.interviews import questions
from hirevion_core.interviews.questions import QuestionFields, QuestionFilters
from hirevion_core.models import Question, QuestionVersion

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]

BASE = QuestionFields(
    text="Explain how Python's garbage collector handles reference cycles.",
    skill_name="py",
    difficulty="medium",
    type="conceptual",
    expected_concepts=("reference counting", "cycle detector"),
    rubric=(
        {"criterion": "Correctness", "weight": 60},
        {"criterion": "Depth", "weight": 40},
    ),
    time_limit_seconds=240,
    follow_up_rules=({"when": "partial", "prompt": "What triggers a collection?"},),
)


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["recruiter"])
    return Actor(user, organization, frozenset(permissions_for(["recruiter"])))


async def test_a_question_is_versioned_and_never_rewritten(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        created = await questions.create_question(session, acme, BASE)
        assert (created.question.category, created.question.status) == ("technical", "approved")
        assert created.version.skill_name == "Python"  # normalised to the taxonomy
        assert created.version.skill_id is not None

        edited = await questions.update_question(
            session, acme, created.question.id, replace(BASE, difficulty="hard")
        )
        assert (edited.question.current_version, edited.version.difficulty) == (2, "hard")
        versions = await questions.list_versions(session, created.question.id)
        assert [(v.version, v.difficulty) for v in versions] == [(1, "medium"), (2, "hard")]


async def test_fields_are_checked(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        for fields, code in (
            (replace(BASE, text="Why?"), "text-too-short"),
            (replace(BASE, type="riddle"), "invalid-type"),
            (
                replace(BASE, rubric=({"criterion": "Correctness", "weight": 50},)),
                "rubric-total",
            ),
            (replace(BASE, follow_up_rules=({"when": "always", "prompt": "x"},)), "invalid-rule"),
            (replace(BASE, type="coding", coding={"languages": ["cobol"]}), "invalid-language"),
        ):
            with pytest.raises(Invalid) as refusal:
                await questions.create_question(session, acme, fields)
            assert refusal.value.code == code


async def test_drafts_need_approval_before_use_and_archived_ones_hide(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        draft = await questions.create_question(session, acme, BASE, status="draft", source="ai")
        ref = [(draft.question.id, 1)]
        with pytest.raises(Invalid) as refusal:
            await questions.require_usable(session, ref)
        assert refusal.value.code == "question-not-approved"

        await questions.approve(session, acme, draft.question.id)
        await questions.require_usable(session, ref)

        await questions.archive(session, acme, draft.question.id)
        listed = (await session.scalars(questions.questions_statement(QuestionFilters()))).all()
        assert draft.question.id not in [q.id for q in listed]
        with pytest.raises(Conflict):
            await questions.update_question(session, acme, draft.question.id, BASE)


async def test_the_library_filters(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        python = await questions.create_question(session, acme, BASE)
        design = await questions.create_question(
            session,
            acme,
            replace(
                BASE,
                text="Design a URL shortener that serves a billion redirects a day.",
                skill_name="System design",
                type="system_design",
                rubric=(),
            ),
        )

        async def ids(filters: QuestionFilters) -> list[UUID]:
            return [q.id for q in (await session.scalars(questions.questions_statement(filters)))]

        assert await ids(QuestionFilters(category="system_design")) == [design.question.id]
        assert await ids(QuestionFilters(skill="python")) == [python.question.id]
        assert await ids(QuestionFilters(query="url shortener")) == [design.question.id]
        assert set(await ids(QuestionFilters(difficulty="medium"))) == {
            python.question.id,
            design.question.id,
        }
        stored = await session.scalar(
            select(QuestionVersion).where(QuestionVersion.question_id == design.question.id)
        )
        assert stored is not None and stored.rubric == []
        assert (await session.get_one(Question, design.question.id)).category == "system_design"
