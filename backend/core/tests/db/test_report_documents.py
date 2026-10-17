"""The reports (SP-17; PRD §68, §69, §99): the interview report's thirteen sections and the
proctoring report's fourteen, populated from a finished interview; the coding report saying what
is missing; and the candidate-visible report, which carries nothing internal."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.evaluation.service import evaluate_interview
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.models import Interview
from hirevion_core.proctoring.catalogue import EVENTS
from hirevion_core.reports import interview as interview_report
from hirevion_core.reports import proctoring as proctoring_report
from hirevion_core.reports import visible
from hirevion_core.reports.blocks import digest
from hirevion_core.reports.coding import coding_report
from hirevion_core.reports.data import InterviewData, load_interview_data
from hirevion_core.reports.html import render_html
from hirevion_core.reports.labels import EVENT_LABELS, SECTION_OF_EVENT

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def actor(org: UUID, user: UUID, *roles: str) -> Actor:
    return Actor(user, org, frozenset(permissions_for(roles)))


async def evaluated(app_db: Database, scene: Any) -> None:
    ai = build_ai(AiSettings(profile="mock"), app_db)  # type: ignore[call-arg]
    await evaluate_interview(app_db, ai.llm, scene.organization_id, scene.interview_id)


async def load(app_db: Database, scene: Any) -> InterviewData:
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        return await load_interview_data(session, interview)


async def test_the_interview_report_has_thirteen_sections_and_each_is_populated(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    data = await load(app_db, scene)
    doc = interview_report.interview_report(data)
    assert [s["key"] for s in doc["sections"]] == list(interview_report.SECTION_KEYS)
    assert len(doc["sections"]) == 13
    status = {s["key"]: s["status"] for s in doc["sections"]}
    # Coding waits for SP-16 and says so; every other section holds what the interview produced.
    assert status.pop("coding_evaluation") == "pending"
    assert set(status.values()) == {"populated"}, status
    assert doc["confidential"] is True and doc["audience"] == "internal"

    sections = {s["key"]: s for s in doc["sections"]}
    assert "SP-16" in sections["coding_evaluation"]["note"]
    skills = next(
        block for block in sections["skill_evaluation"]["blocks"] if block["type"] == "table"
    )
    assert {row[0] for row in skills["rows"]} == {"PostgreSQL", "Python"}
    transcript = sections["transcript"]["blocks"][0]
    assert len(transcript["rows"]) == len(data.segments) and transcript["rows"][0][1] == "AI"
    assert any(b["type"] == "quotes" for b in sections["strengths"]["blocks"])
    # A person's change shows beside the AI's score, with the reason.
    summary = sections["executive_summary"]["blocks"][0]
    communication = next(r for r in summary["rows"] if r["label"] == "Communication")
    assert "6.5" in communication["value"] and "AI:" in communication["value"]
    assert "Spoke clearly but slowly." in str(sections["skill_evaluation"])
    # The timeline mixes the interview's own events with the proctoring and the reviewers'.
    timeline = sections["timeline"]["blocks"][0]["rows"]
    titles = [row[1] for row in timeline]
    assert "Phone seen in the camera" in titles and "Note added" in titles
    assert "Evaluation completed" in titles


async def test_before_the_evaluation_its_sections_wait(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    await add_telemetry(scene)
    doc = interview_report.interview_report(await load(app_db, scene))
    status = {s["key"]: s["status"] for s in doc["sections"]}
    for key in (
        "skill_evaluation",
        "technical_evaluation",
        "communication",
        "strengths",
        "knowledge_gaps",
        "follow_up_performance",
    ):
        assert status[key] == "pending", key
    assert status["questions"] == status["answers"] == status["transcript"] == "populated"


async def test_the_proctoring_report_has_fourteen_populated_sections_and_no_single_score(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, telemetry, _ = await make_reviewed_interview(org)
    doc = proctoring_report.proctoring_report(await load(app_db, scene))
    assert [s["key"] for s in doc["sections"]] == list(proctoring_report.SECTION_KEYS)
    assert len(doc["sections"]) == 14
    assert {s["status"] for s in doc["sections"]} == {"populated"}, {
        s["key"]: s["status"] for s in doc["sections"]
    }
    text = str(doc).lower()
    assert "no single score" in text
    assert "cheating_score" not in text and "risk score" not in text
    sections = {s["key"]: s for s in doc["sections"]}
    # A dismissed event stays in the report, marked as dismissed, with the reviewer's reason.
    gaze = sections["gaze_events"]["blocks"][0]["rows"][0]
    assert gaze[1] == "Looked away from the screen" and gaze[7].startswith(
        "Marked a false positive"
    )
    assert "second monitor" in gaze[7]
    # Every event of the interview is in the timeline, in order.
    rows = sections["timeline"]["blocks"][0]["rows"]
    assert len(rows) == len(telemetry.events)
    assert [row[0] for row in rows] == sorted((row[0] for row in rows), key=_seconds)
    # The server's reason for a severity is given in words.
    assert any("lasted 7 s" in str(row[6]) for row in rows)
    # Evidence is referenced, never embedded.
    evidence = sections["evidence"]["blocks"][0]["rows"]
    assert {row[0] for row in evidence} == {"Process metadata", "Transcript segment"}


def _seconds(clock: str) -> int:
    seconds = 0
    for part in clock.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def test_every_proctoring_event_has_a_label_and_a_report_section() -> None:
    assert set(EVENTS) <= set(EVENT_LABELS)
    assert set(EVENTS) <= set(SECTION_OF_EVENT)


async def test_the_coding_report_says_what_exists_and_what_is_missing(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    await add_telemetry(scene)
    doc = coding_report(await load(app_db, scene))
    sections = {s["key"]: s for s in doc["sections"]}
    assert sections["coding_summary"]["status"] == "pending"
    assert sections["test_results"]["status"] == sections["coding_grade"]["status"] == "pending"
    assert "SP-16" in str(sections["coding_summary"])
    assert sections["coding_questions"]["status"] == "populated"
    code = sections["submitted_code"]["blocks"][0]
    assert code["type"] == "code" and "def decorate" in code["text"]


async def test_html_never_lets_a_candidates_words_become_markup() -> None:
    from hirevion_core.reports import blocks as b

    evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    doc = b.document(
        "interview",
        "Interview report",
        "IV-0001",
        [
            b.section(
                "transcript",
                "Transcript",
                [
                    b.text(evil),
                    b.table("Said", ["Who", "What"], [["Candidate", evil]]),
                    b.quotes([(evil, "Turn 1")]),
                    b.facts([(evil, evil)]),
                    b.code(evil, caption=evil),
                ],
            )
        ],
    )
    html = render_html(doc)
    assert "<script" not in html and "<img" not in html
    assert html.count("&lt;script&gt;") >= 5
    # The policy is an attribute value, so its quotes are entities; the browser reads them back.
    assert "Content-Security-Policy" in html and "default-src &#39;none&#39;" in html
    assert "CONFIDENTIAL" in html


async def test_the_digest_follows_the_content() -> None:
    from hirevion_core.reports import blocks as b

    first = b.document("interview", "T", "S", [b.section("a", "A", [b.text("x")])])
    same = {**first}
    other = b.document("interview", "T", "S", [b.section("a", "A", [b.text("y")])])
    assert digest(first) == digest(same) and digest(first) != digest(other)


async def test_the_candidate_visible_draft_holds_nothing_internal(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, _ = await make_reviewed_interview(org)
    data = await load(app_db, scene)
    draft = visible.draft_items(data)
    assert list(draft) == list(visible.ITEMS) and len(visible.ITEMS) == 5
    text = " ".join(item["text"] for item in draft.values()).lower()
    for internal in (
        "score",
        "/10",
        "flag",
        "proctor",
        "critical",
        "warning",
        "phone",
        "confident on query plans",
        "fits the platform team",
        "spoke clearly",
        data.candidate.email or "no-email",
    ):
        assert internal not in text, internal
    assert draft["completion"]["text"].startswith("You completed your interview for")
    assert "reviewing" in draft["next_step"]["text"]


async def test_a_recruiter_approves_what_the_organisation_allows_and_it_stays_as_released(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
    make_reviewed_interview: Any,
) -> None:
    org = await make_organization("Acme")
    scene, _, recruiter = await make_reviewed_interview(org)
    me = actor(org, recruiter, "recruiter")
    data = await load(app_db, scene)
    async with app_db.tenant(org) as session:
        # By default the organisation shares completion and next step only.
        assert await visible.allowed_items(session, org) == {
            "completion": True,
            "general_feedback": False,
            "technical_feedback": False,
            "coding_feedback": False,
            "next_step": True,
        }
        await visible.save_draft(
            session,
            me,
            data,
            {
                "general_feedback": {"text": "Clear thinking on databases.", "include": True},
                "next_step": {"text": "We will email you by Friday.", "include": True},
            },
        )
        report = await visible.approve(session, me, data)
        assert report.status == "released" and report.approved_by == recruiter
        # The recruiter included general feedback, but the organisation does not share it.
        assert sorted(report.released_items) == ["completion", "next_step"]
        assert report.released_items["next_step"]["text"] == "We will email you by Friday."
        with pytest.raises(Conflict) as edited:
            await visible.save_draft(session, me, data, {})
        assert edited.value.code == "released"
        with pytest.raises(Conflict):
            await visible.approve(session, me, data)
        # Later changes never reach what was released.
        row = await visible.get_report(session, scene.interview_id)
        assert row is not None
        row.items = {**row.items, "next_step": {"text": "Changed after release", "include": True}}
        interview = await session.get_one(Interview, scene.interview_id)
        job = data.job
        doc = visible.visible_document(interview, job, row)
        assert doc["audience"] == "candidate" and doc["confidential"] is False
        assert [s["key"] for s in doc["sections"]] == ["completion", "next_step"]
        assert "Changed after release" not in str(doc)
        with pytest.raises(Invalid):
            await visible.withdraw(session, me, interview, "  ")
        withdrawn = await visible.withdraw(session, me, interview, "Sent to the wrong person")
        assert withdrawn.status == "withdrawn"
        listed = await visible.released_reports(session, interview.candidate_id)
        assert listed == []


async def test_the_organisation_chooses_which_items_may_be_shown(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    make_user: Any,
) -> None:
    org = await make_organization("Acme")
    scene = await make_completed_interview(org)
    admin = await make_user(org, roles=["org_admin"])
    me = actor(org, admin, "org_admin")
    async with app_db.tenant(org) as session:
        saved = await visible.save_allowed_items(session, me, {"general_feedback": True})
        assert saved["general_feedback"] is True and saved["completion"] is True
        with pytest.raises(Invalid):
            await visible.save_allowed_items(session, me, {"salary": True})
    async with app_db.tenant(org) as session:
        assert (await visible.allowed_items(session, org))["general_feedback"] is True
    del scene
