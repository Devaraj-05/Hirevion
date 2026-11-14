"""The reports (SP-17; PRD §68, §69, §99): the interview report's thirteen sections and the
proctoring report's fourteen, populated from a finished interview; the coding report saying what
is missing; and the candidate-visible report, which carries nothing internal."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from hirevion_core.access.actor import Actor
from hirevion_core.access.errors import Conflict, Invalid
from hirevion_core.ai import build_ai
from hirevion_core.ai.settings import AiSettings
from hirevion_core.coding.console import submission
from hirevion_core.db.session import Database
from hirevion_core.evaluation.offline import offline_llm
from hirevion_core.evaluation.service import evaluate_interview
from hirevion_core.identity.permissions import permissions_for
from hirevion_core.ids import uuid7
from hirevion_core.models import (
    CodingTelemetry,
    Interview,
    InterviewQuestion,
    WorkspaceSnapshot,
)
from hirevion_core.proctoring.catalogue import EVENTS
from hirevion_core.reports import interview as interview_report
from hirevion_core.reports import proctoring as proctoring_report
from hirevion_core.reports import visible
from hirevion_core.reports.blocks import digest
from hirevion_core.reports.coding import coding_report, signals_for
from hirevion_core.reports.data import InterviewData, load_interview_data
from hirevion_core.reports.html import render_html
from hirevion_core.reports.labels import EVENT_LABELS, SECTION_OF_EVENT

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def actor(org: UUID, user: UUID, *roles: str) -> Actor:
    return Actor(user, org, frozenset(permissions_for(roles)))


# A recruiter sees the whole report: the proctoring signals and the people's side of the file.
FULL = frozenset(permissions_for(["recruiter"]))


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
    doc = interview_report.interview_report(data, FULL)
    assert [s["key"] for s in doc["sections"]] == list(interview_report.SECTION_KEYS)
    assert len(doc["sections"]) == 13
    status = {s["key"]: s["status"] for s in doc["sections"]}
    # This interview had no coding question and says so; every other section holds what the
    # interview produced.
    assert status.pop("coding_evaluation") == "empty"
    assert set(status.values()) == {"populated"}, status
    assert doc["confidential"] is True and doc["audience"] == "internal"
    # Each table's caption names its scroll region on the web page, so none may repeat.
    captions = [b["caption"] for s in doc["sections"] for b in s["blocks"] if b["type"] == "table"]
    assert len(captions) == len(set(captions)), captions

    sections = {s["key"]: s for s in doc["sections"]}
    assert "no coding question" in str(sections["coding_evaluation"]["blocks"])
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
    doc = interview_report.interview_report(await load(app_db, scene), FULL)
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


async def test_the_interview_report_leaves_out_what_its_reader_may_not_see(
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
    everything = str(interview_report.interview_report(data, FULL))
    interviewer = interview_report.interview_report(data, permissions_for(["interviewer"]))
    limited = str(interviewer)
    # An interviewer reads the interview; the integrity signals need the proctoring permission and
    # the file's status, notes and decisions the candidate permissions.
    assert len(interviewer["sections"]) == 13
    assert "Integrity signals" in everything and "Integrity signals" not in limited

    def summary_labels(doc: Any) -> list[str]:
        section = next(s for s in doc["sections"] if s["key"] == "executive_summary")
        return [row["label"] for row in section["blocks"][0]["rows"]]

    assert "Hiring status" in summary_labels(interview_report.interview_report(data, FULL))
    assert "Hiring status" not in summary_labels(interviewer)
    for private in ("Phone seen in the camera", "Note added", "Hiring manager input"):
        assert private in everything and private not in limited, private
    assert "Evaluation completed" in limited  # the interview's own history stays


async def test_a_score_that_was_zero_is_not_shown_as_missing(
    app_db: Database,
    make_organization: MakeOrganization,
    make_completed_interview: Any,
    add_telemetry: Any,
    make_user: Any,
    make_reviewed_interview: Any,
) -> None:
    from hirevion_core.hiring import scores

    org = await make_organization("Acme")
    scene, _, reviewer = await make_reviewed_interview(org)
    async with app_db.tenant(org) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        recruiter = actor(org, reviewer, "recruiter")
        await scores.change_score(session, recruiter, interview, "overall", None, 0, "Zero")
        await scores.change_score(session, recruiter, interview, "overall", None, 5, "Again")
    doc = interview_report.interview_report(await load(app_db, scene), FULL)
    skills = next(s for s in doc["sections"] if s["key"] == "skill_evaluation")
    changes = next(
        block
        for block in skills["blocks"]
        if block["type"] == "table" and block.get("caption") == "Changes"
    )
    from_zero = [row for row in changes["rows"] if row[5] == "Again"]
    assert from_zero and from_zero[0][3] == "0.0"


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


CODE = (
    "def solve(nums, target):\n"
    "    # One pass with a hash map.\n"
    "    if not nums:\n"
    "        return []\n"
    "    seen = {}\n"
    "    for index, value in enumerate(nums):\n"
    "        if target - value in seen:\n"
    "            return [seen[target - value], index]\n"
    "        seen[value] = index\n"
    "    return []\n"
)


async def _with_coding(app_db: Database, scene: Any, *, submitted: bool = True) -> UUID:
    """Adds an answered coding question to a finished interview: its submission (kept when the
    time ran out) and the console's events."""
    question_id = uuid7()
    asked = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
    async with app_db.tenant(scene.organization_id) as session:
        interview = await session.get_one(Interview, scene.interview_id)
        session.add(
            InterviewQuestion(
                id=question_id,
                organization_id=scene.organization_id,
                interview_id=scene.interview_id,
                position=9,
                kind="coding",
                stage="coding",
                skill="Python",
                difficulty="medium",
                type="coding",
                text="Write solve(nums, target) returning the indices of a pair adding to target.",
                source="library",
                workspace="code",
                languages=["python"],
                status="timed_out",
                asked_at=asked,
                closed_at=asked + timedelta(minutes=10),
            )
        )
        await session.flush()
        if submitted:
            session.add(
                submission(
                    interview, question_id, language="python", code=CODE, source="time_limit"
                )
            )
        for kind, second, chars in (
            ("focus", 1, None),
            ("typing_started", 2, None),
            ("paste", 30, 150),
            ("blur", 60, None),
            ("focus", 150, None),
        ):
            session.add(
                CodingTelemetry(
                    organization_id=scene.organization_id,
                    interview_id=scene.interview_id,
                    question_id=question_id,
                    kind=kind,
                    chars=chars,
                    occurred_at=asked + timedelta(seconds=second),
                )
            )
    return question_id


async def test_a_question_closed_without_a_submission_shows_the_draft_that_was_reviewed(
    app_db: Database, make_organization: MakeOrganization, make_completed_interview: Any
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    question = await _with_coding(app_db, scene, submitted=False)
    async with app_db.tenant(scene.organization_id) as session:
        session.add(
            WorkspaceSnapshot(
                organization_id=scene.organization_id,
                interview_id=scene.interview_id,
                question_id=question,
                kind="code",
                language="python",
                content=CODE,
                size=len(CODE),
            )
        )
    data = await load(app_db, scene)
    sections = {s["key"]: s for s in coding_report(data)["sections"]}
    final = sections["final_code"]["blocks"][0]
    assert final["text"] == CODE and "the last saved text" in final["caption"]
    assert "No code was given" not in str(sections["final_code"])
    # The paste of 150 characters is measured against the reviewed draft, not against nothing.
    assert signals_for(data, next(q for q in data.questions if q.id == question)).paste_share


async def test_without_a_coding_question_the_coding_report_says_so(
    app_db: Database, make_organization: MakeOrganization, make_completed_interview: Any
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    doc = coding_report(await load(app_db, scene))
    sections = {s["key"]: s for s in doc["sections"]}
    assert [s["status"] for s in doc["sections"]] == ["empty"] * 6
    assert sections["coding_questions"]["note"] == "This interview asked no coding questions."
    assert all(s["status"] != "pending" for s in doc["sections"])


async def test_the_coding_report_shows_the_code_every_submission_the_review_and_the_signals(
    app_db: Database, make_organization: MakeOrganization, make_completed_interview: Any
) -> None:
    scene = await make_completed_interview(await make_organization("Acme"))
    await _with_coding(app_db, scene)
    before = {s["key"]: s for s in coding_report(await load(app_db, scene))["sections"]}
    assert before["final_code"]["status"] == "populated"
    assert CODE in before["final_code"]["blocks"][0]["text"]
    assert "kept when the time ran out" in before["final_code"]["blocks"][0]["caption"]
    assert before["submissions"]["status"] == "populated"
    assert before["assessment"]["status"] == "empty"
    assert before["assessment"]["note"] == "The interview hasn't been evaluated yet."
    integrity = str(before["integrity"])
    assert "never proof" in integrity and "Pasted once, 150 characters." in integrity
    assert "Left the code box once, about 90 seconds in all." in integrity

    llm, _ = offline_llm()
    await evaluate_interview(app_db, llm, scene.organization_id, scene.interview_id)
    doc = coding_report(await load(app_db, scene))
    sections = {s["key"]: s for s in doc["sections"]}
    assert all(s["status"] == "populated" for s in doc["sections"]), [
        (s["key"], s["status"]) for s in doc["sections"]
    ]
    blocks = sections["assessment"]["blocks"]
    assert "never run" in blocks[0]["text"]
    criteria = next(b for b in blocks if b["type"] == "table")
    assert [row[0] for row in criteria["rows"]][3] == "Time complexity (estimated)"
    assert criteria["caption"].startswith("Criteria for question ")
    quotes = next(b for b in blocks if b["type"] == "quotes")
    assert all(" · line " in item["source"] for item in quotes["items"])
    assert all(item["text"] in CODE for item in quotes["items"])
    summary = str(sections["coding_summary"])
    assert "estimated O(n) time" in summary


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
