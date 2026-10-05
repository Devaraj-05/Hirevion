"""Interview templates: versions, validation, defaults and the skill matrix (SP-06 Task 3)."""

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.interviews import questions, templates
from hirevion_core.interviews.questions import QuestionFields
from hirevion_core.interviews.templates import TemplateFields, allocate

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
SKILLS = (
    {"name": "py", "weight": 50},
    {"name": "PostgreSQL", "weight": 30},
    {"name": "Go", "weight": 20},
)


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["recruiter"])
    return Actor(user, organization, frozenset(permissions_for(["recruiter"])))


def test_largest_remainder_allocation() -> None:
    assert allocate(10, [50, 30, 20]) == [5, 3, 2]
    assert allocate(5, [20, 50, 30]) == [1, 3, 1]  # ties go to the earlier share
    assert sum(allocate(7, [34, 33, 33])) == 7


async def test_a_template_starts_from_the_defaults_and_versions_on_edit(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        created = await templates.create_template(
            session, acme, TemplateFields(name="Senior Python", skills=SKILLS)
        )
        first = created.version
        assert (first.version, first.duration_minutes, first.question_count) == (1, 45, 10)
        assert first.difficulty == {"easy": 20, "medium": 50, "hard": 30}
        assert [s["name"] for s in first.skills] == ["Python", "PostgreSQL", "Go"]
        assert sum(r["weight"] for r in first.rubric) == 100 and len(first.rubric) == 8

        edited = await templates.update_template(
            session,
            acme,
            created.template.id,
            TemplateFields(duration_minutes=60, proctoring_level="strict", third_eye="required"),
        )
        assert (edited.version.version, edited.version.duration_minutes) == (2, 60)
        assert edited.version.skills == first.skills  # untouched fields carry over
        versions = await templates.list_versions(session, created.template.id)
        assert [(v.version, v.duration_minutes, v.proctoring_level) for v in versions] == [
            (1, 45, "standard"),
            (2, 60, "strict"),
        ]


async def test_templates_are_checked(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        for fields, code in (
            (TemplateFields(name="T", skills=({"name": "Go", "weight": 60},)), "skills-total"),
            (
                TemplateFields(
                    name="T", skills=SKILLS, difficulty={"easy": 50, "medium": 50, "hard": 10}
                ),
                "difficulty-total",
            ),
            (TemplateFields(name="T", skills=SKILLS, duration_minutes=5), "invalid-duration"),
            (
                TemplateFields(
                    name="T", skills=SKILLS, coding={"enabled": True, "languages": ["rust"]}
                ),
                "invalid-language",
            ),
            (TemplateFields(name="T", skills=SKILLS, question_types=()), "types-required"),
        ):
            with pytest.raises(Invalid) as refusal:
                await templates.create_template(session, acme, fields)
            assert refusal.value.code == code
        await templates.create_template(session, acme, TemplateFields(name="Same", skills=SKILLS))
    with pytest.raises(Conflict):
        async with app_db.tenant(acme.organization_id) as session:
            await templates.create_template(
                session, acme, TemplateFields(name="same", skills=SKILLS)
            )


async def test_only_approved_questions_can_be_pinned(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        draft = await questions.create_question(
            session,
            acme,
            QuestionFields(
                text="Explain Python's GIL and when it matters.",
                skill_name="Python",
                difficulty="medium",
                type="conceptual",
            ),
            status="draft",
        )
        with pytest.raises(Invalid) as refusal:
            await templates.create_template(
                session,
                acme,
                TemplateFields(name="T", skills=SKILLS, questions=((draft.question.id, 1),)),
            )
        assert refusal.value.code == "question-not-approved"


async def test_organisation_defaults_apply_to_new_templates(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        built_in = await templates.interview_defaults(session)
        assert (built_in["duration_minutes"], built_in["proctoring_level"]) == (45, "standard")
        await templates.save_interview_defaults(
            session, acme, {"duration_minutes": 30, "third_eye": "required"}
        )
        created = await templates.create_template(
            session, acme, TemplateFields(name="Short", skills=SKILLS)
        )
        assert (created.version.duration_minutes, created.version.third_eye) == (30, "required")
        with pytest.raises(Invalid):
            await templates.save_interview_defaults(session, acme, {"question_count": 99})


async def test_the_skill_matrix_shows_targets_and_library_gaps(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        for difficulty in ("easy", "medium", "medium"):
            await questions.create_question(
                session,
                acme,
                QuestionFields(
                    text=f"A {difficulty} question about Python internals and the runtime.",
                    skill_name="Python",
                    difficulty=difficulty,
                    type="technical",
                ),
            )
        created = await templates.create_template(
            session, acme, TemplateFields(name="Senior Python", skills=SKILLS)
        )
        matrix = await templates.skill_matrix(session, created.version)
    python = matrix[0]
    assert (python.skill, python.weight, python.questions) == ("Python", 50, 5)
    assert python.by_difficulty == {"easy": 1, "medium": 3, "hard": 1}
    assert python.available == {"easy": 1, "medium": 2, "hard": 0}
    assert python.gaps == {"medium": 1, "hard": 1}
    assert [row.questions for row in matrix] == [5, 3, 2]
