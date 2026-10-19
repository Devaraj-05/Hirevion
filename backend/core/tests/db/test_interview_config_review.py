"""D1 code review of interview configuration (SP-06): a draft is never usable until a person
approved the version they pin, templates and defaults change only what was sent, edits take
turns, and AI drafts are what was asked for."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.db.session import Database
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.interviews import generation, questions, templates
from hirevion_core.interviews.generation import (
    GeneratedQuestion,
    GeneratedQuestions,
    GenerationRequest,
)
from hirevion_core.interviews.questions import QuestionFields
from hirevion_core.interviews.templates import TemplateFields
from hirevion_core.models import Candidate, OrganizationSettings, Question

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]
SKILLS = [{"name": "Python", "weight": 100}]


def fields(
    text_: str = "Explain how Python's garbage collector finds reference cycles.", **kw: Any
):
    values: dict[str, Any] = {
        "text": text_,
        "skill_name": "Python",
        "difficulty": "medium",
        "type": "conceptual",
    }
    return QuestionFields(**{**values, **kw})


@pytest.fixture
async def acme(make_organization: MakeOrganization, make_user) -> Actor:
    organization = await make_organization("Acme")
    user = await make_user(organization, roles=["recruiter"])
    return Actor(user, organization, frozenset(permissions_for(["recruiter"])))


async def test_only_the_version_a_person_approved_or_a_later_one_can_be_pinned(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        draft = await questions.create_question(
            session, acme, fields(), status="draft", source="ai"
        )
        qid = draft.question.id
        await questions.update_question(
            session, acme, qid, fields("Explain how CPython finds reference cycles in memory.")
        )
        await questions.approve(session, acme, qid, version=2)
        with pytest.raises(Invalid) as refusal:  # the raw AI text of version 1
            await questions.require_usable(session, [(qid, 1)])
        assert refusal.value.code == "question-not-approved"
        await questions.require_usable(session, [(qid, 2)])
        later = await questions.update_question(
            session, acme, qid, fields("Explain how CPython finds reference cycles in memory?!")
        )
        await questions.require_usable(session, [(qid, later.version.version)])
        with pytest.raises(Invalid):  # a version that doesn't exist
            await questions.require_usable(session, [(qid, 9)])


async def test_approval_names_the_version_the_reviewer_saw(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        draft = await questions.create_question(
            session, acme, fields(), status="draft", source="ai"
        )
        await questions.update_question(session, acme, draft.question.id, fields("A new wording."))
        with pytest.raises(Conflict) as stale:
            await questions.approve(session, acme, draft.question.id, version=1)
        assert stale.value.code == "question-changed"
        assert (await session.get_one(Question, draft.question.id)).status == "draft"


async def test_a_restored_question_must_be_approved_again(app_db: Database, acme: Actor) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        made = await questions.create_question(session, acme, fields())  # manual: approved
        qid = made.question.id
        await questions.require_usable(session, [(qid, 1)])
        await questions.archive(session, acme, qid)
        restored = await questions.restore(session, acme, qid)
        assert (restored.status, restored.approved_at, restored.approved_by) == (
            "draft",
            None,
            None,
        )
        with pytest.raises(Invalid):
            await questions.require_usable(session, [(qid, 1)])


async def test_an_ai_question_is_a_draft_whatever_the_caller_asks_for(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        made = await questions.create_question(session, acme, fields(), source="ai")
        assert made.question.status == "draft" and made.question.approved_by is None


async def test_two_edits_of_a_question_or_template_at_once_both_land(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        question = await questions.create_question(session, acme, fields())
        template = await templates.create_template(
            session, acme, TemplateFields(name="Backend", skills=SKILLS)
        )

    async def edit_question(wording: str) -> None:
        async with app_db.tenant(acme.organization_id) as session:
            await questions.update_question(session, acme, question.question.id, fields(wording))
            await asyncio.sleep(0.2)

    async def edit_template(minutes: int) -> None:
        async with app_db.tenant(acme.organization_id) as session:
            await templates.update_template(
                session, acme, template.template.id, TemplateFields(duration_minutes=minutes)
            )
            await asyncio.sleep(0.2)

    await asyncio.gather(
        edit_question("Explain the first thing in detail."),
        edit_question("Explain the second thing in detail."),
        edit_template(30),
        edit_template(60),
    )
    async with app_db.tenant(acme.organization_id) as session:
        assert [
            v.version for v in await questions.list_versions(session, question.question.id)
        ] == [
            1,
            2,
            3,
        ]
        assert [
            v.version for v in await templates.list_versions(session, template.template.id)
        ] == [
            1,
            2,
            3,
        ]


# Templates


async def test_a_template_rubric_names_each_dimension_once_and_pins_fit_the_count(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        twice = [{"dimension": "relevance", "weight": 50}, {"dimension": "relevance", "weight": 50}]
        with pytest.raises(Invalid) as refusal:
            await templates.create_template(
                session, acme, TemplateFields(name="A", skills=SKILLS, rubric=twice)
            )
        assert refusal.value.code == "invalid-rubric"
        first = await questions.create_question(session, acme, fields())
        second = await questions.create_question(session, acme, fields("Another question to ask."))
        template = await templates.create_template(
            session,
            acme,
            TemplateFields(
                name="B",
                skills=SKILLS,
                question_count=2,
                questions=[(first.question.id, 1), (second.question.id, 1)],
            ),
        )
        # Lowering the count below the questions already pinned is refused.
        with pytest.raises(Invalid) as too_many:
            await templates.update_template(
                session, acme, template.template.id, TemplateFields(question_count=1)
            )
        assert too_many.value.code == "too-many-questions"
        # The same question twice, at two versions, is one question asked twice.
        newer = await questions.update_question(
            session, acme, first.question.id, fields("Explain it, differently this time.")
        )
        with pytest.raises(Invalid) as twice_pinned:
            await templates.update_template(
                session,
                acme,
                template.template.id,
                TemplateFields(
                    questions=[(first.question.id, 1), (first.question.id, newer.version.version)]
                ),
            )
        assert twice_pinned.value.code == "duplicate-question"


async def test_coding_time_fits_the_interview_and_languages_are_listed_once(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        with pytest.raises(Invalid) as refusal:
            await templates.create_template(
                session,
                acme,
                TemplateFields(
                    name="Coding",
                    skills=SKILLS,
                    duration_minutes=15,
                    coding={"enabled": True, "languages": ["python"], "minutes": 90},
                ),
            )
        assert refusal.value.code == "invalid-coding-minutes"
        made = await templates.create_template(
            session,
            acme,
            TemplateFields(
                name="Coding 2",
                skills=SKILLS,
                coding={"enabled": True, "languages": ["python", "Python", "sql"], "minutes": 20},
            ),
        )
        assert made.version.coding["languages"] == ["python", "sql"]


async def test_saving_a_template_with_nothing_new_writes_no_version(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        made = await templates.create_template(
            session, acme, TemplateFields(name="Backend", skills=SKILLS)
        )
        same = await templates.update_template(
            session, acme, made.template.id, TemplateFields(duration_minutes=45, skills=SKILLS)
        )
        assert same.version.version == 1
        described = await templates.update_template(
            session, acme, made.template.id, TemplateFields(description="For backend roles")
        )
        assert described.version.version == 1 and described.template.description
        changed = await templates.update_template(
            session, acme, made.template.id, TemplateFields(duration_minutes=60)
        )
        assert changed.version.version == 2


async def test_a_partial_nested_setting_changes_only_what_was_sent(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        made = await templates.create_template(
            session,
            acme,
            TemplateFields(
                name="Quiet",
                skills=SKILLS,
                recording={"screen": True, "camera": False, "audio": True},
                coding={"enabled": True, "languages": ["sql"], "minutes": 25},
            ),
        )
        edited = await templates.update_template(
            session,
            acme,
            made.template.id,
            TemplateFields(recording={"screen": False}, coding={"minutes": 30}),
        )
        assert edited.version.recording == {"screen": False, "camera": False, "audio": True}
        assert edited.version.coding == {"enabled": True, "languages": ["sql"], "minutes": 30}
        saved = await templates.save_interview_defaults(
            session, acme, {"recording": {"camera": False}}
        )
        again = await templates.save_interview_defaults(
            session, acme, {"recording": {"audio": False}}
        )
        assert saved["recording"] == {"screen": True, "camera": False, "audio": True}
        assert again["recording"] == {"screen": True, "camera": False, "audio": False}


async def test_saving_defaults_audits_old_and_new_and_keeps_only_what_was_set(
    app_db: Database, admin_engine: AsyncEngine, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        await templates.save_interview_defaults(session, acme, {"proctoring_level": "strict"})
        await templates.save_interview_defaults(session, acme, {"proctoring_level": "strict"})
        row = await session.scalar(select(OrganizationSettings))
        assert row is not None and row.interview_defaults == {"proctoring_level": "strict"}
        first_stamp = row.updated_at
    await asyncio.sleep(0.05)
    async with app_db.tenant(acme.organization_id) as session:  # (now() is the transaction's)
        await templates.save_interview_defaults(session, acme, {"question_count": 12})
        row = await session.scalar(select(OrganizationSettings))
        assert row is not None and row.updated_at > first_stamp
    async with admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT details FROM audit_logs WHERE organization_id = :org "
                    "AND action = 'interview_defaults.changed' ORDER BY seq"
                ),
                {"org": acme.organization_id},
            )
        ).all()
    assert len(rows) == 2  # the repeated save changed nothing, so left no entry
    assert rows[0].details["changed"] == {"proctoring_level": {"from": "standard", "to": "strict"}}
    assert rows[1].details["changed"] == {"question_count": {"from": 10, "to": 12}}


async def test_the_skill_matrix_counts_only_questions_of_the_allowed_types(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        await questions.create_question(session, acme, fields(type="conceptual"))
        await questions.create_question(
            session, acme, fields("Design a cache for sessions.", type="system_design")
        )
        made = await templates.create_template(
            session,
            acme,
            TemplateFields(name="Concepts", skills=SKILLS, question_types=["conceptual"]),
        )
        [row] = await templates.skill_matrix(session, made.version)
        assert row.available["medium"] == 1  # the system-design question isn't for this template


async def test_text_with_a_nul_is_refused_not_a_database_error(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        with pytest.raises(Invalid):
            await questions.create_question(
                session, acme, fields("Explain the GIL.\x00 In detail.")
            )


# AI drafts


def generated(text_: str, skill: str = "Python", kind: str = "conceptual") -> GeneratedQuestion:
    return GeneratedQuestion(
        text=text_, skill_name=skill, difficulty="medium", type=kind, expected_concepts=[]
    )


async def test_drafts_are_no_more_than_asked_for_and_other_scripts_are_not_duplicates(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        result = await generation.save_drafts(
            session,
            acme,
            GeneratedQuestions(
                questions=[
                    generated("What is C++ used for in this role?", "C++"),
                    generated("What is C# used for in this role?", "C#"),
                    generated("तपाइं Python के बारे में बताइए"),
                    generated("A fourth question about Python typing?"),
                ]
            ),
            [],
            model="fake",
            refs={},
            limit=3,
        )
        assert [d.version.skill_name for d in result.drafts] == ["C++", "C#", "Python"]
        assert all(d.question.status == "draft" for d in result.drafts)
        assert result.skipped == 1  # the one over the limit


async def test_the_candidate_text_sent_to_the_ai_has_no_contact_details(
    app_db: Database, acme: Actor
) -> None:
    async with app_db.tenant(acme.organization_id) as session:
        candidate = Candidate(
            organization_id=acme.organization_id,
            name="Priya Nair",
            profile={
                "positions": [{"title": "Engineer", "company": "Acme"}],
                "projects": [
                    {
                        "name": "Gateway",
                        "description": "Built it; mail priya@x.test or +91 98765 43210",
                    }
                ],
                "achievements": [{"text": "Won a prize, PAN ABCPE1234F"}],
            },
        )
        session.add(candidate)
        await session.flush()
        message, _ = await generation.gather(
            session, GenerationRequest(skills=["Python"], candidate_id=candidate.id)
        )
    for secret in ("priya@x.test", "98765", "ABCPE1234F", "Priya", "Nair"):
        assert secret not in message
    assert "Gateway" in message
