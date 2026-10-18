"""The interview report (PRD §69): thirteen sections, built from the interview's data.

Everything here is internal: it holds scores, integrity signals and the people's decisions, and
never reaches the candidate (their report is `reports.visible`). The AI's scores show beside any
change a person made, with the reason."""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any

from hirevion_core.evaluation.registry import DIMENSIONS
from hirevion_core.reports import blocks as b
from hirevion_core.reports.blocks import Block, Document, Section
from hirevion_core.reports.coding import coding_blocks
from hirevion_core.reports.data import InterviewData
from hirevion_core.reports.labels import (
    DIMENSION_LABELS,
    HIRING_LABELS,
    SEVERITY_LABELS,
    STATUS_LABELS,
)
from hirevion_core.reports.timeline import Entry, allowed_sources, interview_entries

SECTION_KEYS = (
    "executive_summary",
    "interview_metadata",
    "questions",
    "answers",
    "skill_evaluation",
    "technical_evaluation",
    "coding_evaluation",
    "communication",
    "strengths",
    "knowledge_gaps",
    "follow_up_performance",
    "transcript",
    "timeline",
)
NOT_EVALUATED = "The evaluation hasn't finished, so there is nothing to show here yet."
TIMELINE_SOURCES = (
    "interview",
    "transcript",
    "coding",
    "proctoring",
    "recording",
    "evaluation",
    "recruiter",
)


def evidence_label(item: dict[str, Any]) -> str:
    return f"Turn {item.get('seq')} at {b.clock(item.get('start_ms'))}"


def quote_items(evidence: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(str(item["quote"]), evidence_label(item)) for item in evidence]


def _evaluation_note(data: InterviewData) -> str | None:
    return None if data.evaluation is not None else NOT_EVALUATED


def _pending(key: str, title: str, data: InterviewData) -> Section:
    return b.section(
        key, title, [b.notice(NOT_EVALUATED)], pending=True, note=_evaluation_note(data)
    )


def integrity_line(data: InterviewData) -> str:
    if not data.events:
        return "No proctoring events were recorded."
    counts = {severity: 0 for severity in SEVERITY_LABELS}
    for event in data.events:
        counts[event.severity] = counts.get(event.severity, 0) + 1
    outcomes = {"confirmed": 0, "false_positive": 0, "not_relevant": 0}
    for review in data.reviews.values():
        outcomes[review.outcome] += 1
    return (
        f"{counts['CRITICAL']} critical, {counts['WARNING']} warning and {counts['INFO']} "
        f"information events. {len(data.reviews)} reviewed ({outcomes['confirmed']} confirmed, "
        f"{outcomes['false_positive']} false positives, {outcomes['not_relevant']} not relevant). "
        "These are signals for a reviewer, not a verdict."
    )


def _score_text(value: Any) -> str:
    """The shown score, with the AI's beside it when a person changed it."""
    if value is None:
        return b.DASH
    if value.change is None:
        return b.score(value.value)
    return f"{b.score(value.value)} (AI: {b.score(value.ai)})"


def executive_summary(data: InterviewData, sources: Collection[str]) -> Section:
    interview, evaluation, view = data.interview, data.evaluation, data.scores
    rows: list[tuple[str, str | None]] = [
        ("Candidate", data.candidate.name),
        ("Role", f"{data.job.title}"),
        ("Interview", f"IV-{interview.number:04d} ({STATUS_LABELS.get(interview.status)})"),
    ]
    if "recruiter" in sources:  # the people's side of the file: status, decisions, notes
        rows.append(("Hiring status", HIRING_LABELS[data.application.hiring_status]))
    content: list[Block] = []
    if evaluation is None or view is None:
        content += [b.facts(rows), b.notice(NOT_EVALUATED)]
    else:
        rows += [
            ("Overall score", _score_text(view.overall) + " of 10"),
            ("Communication", _score_text(view.communication) + " of 10"),
            ("Evaluation flags", ", ".join(evaluation.flags) or "None"),
        ]
        content.append(b.facts(rows))
        content.append(
            b.table(
                "Skill scores",
                ["Skill", "Score", "Questions"],
                [
                    [
                        item["skill"],
                        _score_text(view.skills.get(item["skill"])),
                        str(item.get("questions", 0)),
                    ]
                    for item in evaluation.skills
                ],
            )
        )
        summary = evaluation.summary
        if summary.get("strengths"):
            content += [
                b.text("Strengths"),
                b.bullets([item["text"] for item in summary["strengths"][:3]]),
            ]
        if summary.get("knowledge_gaps"):
            content += [
                b.text("Knowledge gaps"),
                b.bullets([item["text"] for item in summary["knowledge_gaps"][:3]]),
            ]
    if "proctoring" in sources:
        content.append(b.text("Integrity signals: " + integrity_line(data), muted=True))
    content.append(
        b.notice(
            "The scores and summaries were produced by AI from the transcript and checked "
            "against it. People review them, and hiring decisions are made by people."
        )
    )
    return b.section(
        "executive_summary",
        "Executive summary",
        content,
        note=_evaluation_note(data),
    )


def interview_metadata(data: InterviewData) -> Section:
    interview, run, evaluation = data.interview, data.run, data.evaluation
    tz = data.timezone
    policy = interview.policy or {}
    recording = policy.get("recording") or {}
    actual = (
        int((interview.ended_at - interview.started_at).total_seconds() * 1000)
        if interview.ended_at and interview.started_at
        else None
    )
    rows: list[tuple[str, str | None]] = [
        ("Reference", f"IV-{interview.number:04d}"),
        ("Candidate", data.candidate.name),
        ("Email", data.candidate.email),
        ("Job", data.job.title),
        ("Template", f"{data.template_name} (version {interview.template_version})"),
        ("Status", STATUS_LABELS.get(interview.status, interview.status)),
        ("Window opened", b.when(interview.starts_at, tz)),
        ("Window closed", b.when(interview.expires_at, tz)),
        ("Started", b.when(interview.started_at, tz)),
        ("Ended", b.when(interview.ended_at, tz)),
        ("Planned length", f"{interview.duration_minutes} min"),
        ("Actual length", b.minutes(actual)),
        ("Answers given", str(run.mode).capitalize() if run else None),
        ("Interruptions", str(run.interruptions) if run else None),
        ("Reconnections", str(run.reconnects) if run else None),
        ("Recorded", ", ".join(name for name, on in recording.items() if on) or "Nothing"),
        ("Proctoring level", str(policy.get("proctoring_level") or "")),
        ("Third eye", str(policy.get("third_eye") or "")),
        ("Language", interview.locale),
        ("Time zone", tz),
    ]
    if evaluation is not None:
        pinned = evaluation.pinned or {}
        rows += [
            ("Evaluated", b.when(evaluation.completed_at, tz)),
            ("Evaluation version", evaluation.evaluation_version),
            ("Question prompt", evaluation.prompt_version),
            ("Rubric", evaluation.rubric_version),
            ("Model", evaluation.model),
            ("Synthesis prompt", pinned.get("synthesis_prompt_version")),
        ]
    return b.section("interview_metadata", "Interview metadata", [b.facts(rows)])


def questions_section(data: InterviewData) -> Section:
    tz = data.timezone
    rows = [
        [
            str(q.position),
            b.label(q.kind),
            q.skill,
            q.difficulty,
            b.label(q.type or ""),
            b.label(q.source),
            b.when(q.asked_at, tz),
            q.text,
        ]
        for q in data.questions
    ]
    return b.section(
        "questions",
        "Questions",
        [
            b.table(
                "Questions asked, in order",
                ["#", "Kind", "Skill", "Difficulty", "Type", "Source", "Asked", "Question"],
                rows,
            )
        ],
    )


def answers_section(data: InterviewData) -> Section:
    rows: list[list[str | None]] = []
    for q in data.questions:
        for answer in data.answers.get(q.id, []):
            notes = [*answer.flags, *(["late"] if answer.late else [])]
            rows.append(
                [str(q.position), q.text, answer.text, answer.mode, ", ".join(notes) or None]
            )
    return b.section(
        "answers",
        "Answers",
        [b.table("The candidate's answers", ["#", "Question", "Answer", "Mode", "Notes"], rows)],
        note=None if rows else "No answers were recorded.",
    )


def skill_evaluation(data: InterviewData) -> Section:
    evaluation, view = data.evaluation, data.scores
    if evaluation is None or view is None:
        return _pending("skill_evaluation", "Skill evaluation", data)
    content: list[Block] = [
        b.table(
            "Skill scores",
            ["Skill", "Weight", "Score", "Questions", "Verified evidence"],
            [
                [
                    item["skill"],
                    f"{item.get('weight', 0):g}",
                    _score_text(view.skills.get(item["skill"])),
                    str(item.get("questions", 0)),
                    "Yes" if item.get("supported") else "No (score capped)",
                ]
                for item in evaluation.skills
            ],
        )
    ]
    for item in evaluation.skills:
        if item.get("evidence"):
            content += [
                b.text(f"{item['skill']}: evidence"),
                b.quotes(quote_items(item["evidence"])),
            ]
    if view.changes:
        content += [
            b.text("Scores changed by people"),
            b.table(
                "Changes",
                ["When", "By", "What", "From", "To", "Reason"],
                [
                    [
                        b.when(change.created_at, data.timezone),
                        data.person(change.changed_by),
                        change.target or b.label(change.scope),
                        b.score(
                            float(change.previous_score)
                            if change.previous_score is not None
                            else None
                        ),
                        b.score(float(change.new_score)),
                        change.reason,
                    ]
                    for change in view.changes
                ],
            ),
        ]
    return b.section("skill_evaluation", "Skill evaluation", content)


def technical_evaluation(data: InterviewData) -> Section:
    if data.evaluation is None:
        return _pending("technical_evaluation", "Technical evaluation", data)
    rows: list[list[str | None]] = []
    missed: list[str] = []
    for q in data.questions:
        scored = data.question_evaluations.get(q.id)
        if scored is None or not q.skill:
            continue
        shown = data.scores.questions.get(str(q.id)) if data.scores else None
        rows.append(
            [
                str(q.position),
                q.skill,
                b.label(scored.kind),
                *[
                    b.score(float(scored.dimensions[name]["score"]))
                    + ("" if scored.dimensions[name].get("supported") else "*")
                    for name in DIMENSIONS
                ],
                _score_text(shown) if shown else b.score(float(scored.overall_score)),
            ]
        )
        if scored.missing_concepts:
            missed.append(f"Question {q.position}: {', '.join(scored.missing_concepts)}")
    content: list[Block] = [
        b.table(
            "Each technical question on the eight dimensions",
            ["#", "Skill", "Kind", *[DIMENSION_LABELS[name] for name in DIMENSIONS], "Overall"],
            rows,
        ),
        b.text(
            "* A dimension without a verified quote from the candidate is capped at 5.", muted=True
        ),
    ]
    if missed:
        content += [b.text("Concepts the answers missed"), b.bullets(missed)]
    return b.section("technical_evaluation", "Technical evaluation", content)


def coding_evaluation(data: InterviewData) -> Section:
    return b.section(
        "coding_evaluation",
        "Coding evaluation",
        coding_blocks(data),
        pending=True,
        note="Coding questions, test runs and grading arrive with the coding service (SP-16).",
    )


def communication(data: InterviewData) -> Section:
    evaluation, view = data.evaluation, data.scores
    if evaluation is None or view is None:
        return _pending("communication", "Communication", data)
    item = evaluation.summary.get("communication", {})
    cited = item.get("summary") or {}
    content: list[Block] = [
        b.facts(
            [
                ("Score", _score_text(view.communication) + " of 10"),
                ("Verified evidence", "Yes" if item.get("supported") else "No (score capped)"),
            ]
        )
    ]
    if cited.get("summary"):
        content.append(b.text(cited["summary"]))
    if item.get("evidence"):
        content += [b.text("Evidence"), b.quotes(quote_items(item["evidence"]))]
    return b.section("communication", "Communication", content)


def _findings(key: str, title: str, label: str, data: InterviewData) -> Section:
    if data.evaluation is None:
        return _pending(key, title, data)
    content: list[Block] = []
    for number, finding in enumerate(data.evaluation.summary.get(label, []), start=1):
        skill = f" ({finding['skill']})" if finding.get("skill") else ""
        content.append(b.text(f"{number}. {finding['text']}{skill}"))
        if finding.get("evidence"):
            content.append(b.quotes(quote_items(finding["evidence"])))
    return b.section(
        key,
        title,
        content,
        note=None if content else f"The evaluation found no {title.lower()}.",
    )


def strengths(data: InterviewData) -> Section:
    return _findings("strengths", "Strengths", "strengths", data)


def knowledge_gaps(data: InterviewData) -> Section:
    return _findings("knowledge_gaps", "Knowledge gaps", "knowledge_gaps", data)


def follow_up_performance(data: InterviewData) -> Section:
    if data.evaluation is None:
        return _pending("follow_up_performance", "Follow-up performance", data)
    item = data.evaluation.summary.get("follow_up_performance", {})
    content: list[Block] = [
        b.facts(
            [
                ("Follow-up questions asked", str(item.get("asked", 0))),
                ("Average follow-up score", b.score(item.get("mean"))),
                ("Average main-question score", b.score(item.get("main_mean"))),
                ("Difference", b.score(item.get("delta"))),
            ]
        )
    ]
    cited = item.get("summary") or {}
    if cited.get("summary"):
        content.append(b.text(cited["summary"]))
    if cited.get("evidence"):
        content.append(b.quotes(quote_items(cited["evidence"])))
    numbers = {q.id: q.position for q in data.questions}
    follow_ups = [q for q in data.questions if q.kind == "follow_up"]
    if follow_ups:
        content.append(
            b.table(
                "Follow-up questions",
                ["#", "Follows", "Question", "Score"],
                [
                    [
                        str(q.position),
                        str(numbers.get(q.parent_id, "")) if q.parent_id else None,
                        q.text,
                        b.score(
                            float(data.question_evaluations[q.id].overall_score)
                            if q.id in data.question_evaluations
                            else None
                        ),
                    ]
                    for q in follow_ups
                ],
            )
        )
    return b.section(
        "follow_up_performance",
        "Follow-up performance",
        content,
        note=None if item.get("asked") else "No follow-up questions were asked.",
    )


def transcript(data: InterviewData) -> Section:
    rows = [
        [b.clock(s.start_ms), "AI" if s.speaker == "ai" else "Candidate", s.text]
        for s in data.segments
    ]
    return b.section(
        "transcript",
        "Transcript",
        [b.table("The conversation", ["Time", "Speaker", "Said"], rows)],
        note=None if rows else "There is no transcript.",
    )


def timeline_rows(entries: list[Entry], data: InterviewData) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    for entry in sorted(entries, key=lambda e: e.at):
        when = (
            b.clock(entry.offset_ms)
            if entry.offset_ms is not None and entry.offset_ms >= 0
            else b.when(entry.at, data.timezone)
        )
        rows.append([when, entry.title, entry.detail, b.label(entry.source)])
    return rows


def timeline(data: InterviewData, sources: Collection[str]) -> Section:
    entries = interview_entries(
        data, [source for source in TIMELINE_SOURCES if source in sources], min_severity="WARNING"
    )
    return b.section(
        "timeline",
        "Timeline",
        [
            b.table(
                "What happened, in order (times are from the start of the interview)",
                ["Time", "What", "Detail", "Source"],
                timeline_rows(entries, data),
            )
        ],
    )


def interview_report(
    data: InterviewData,
    permissions: Collection[str],
    *,
    generated_at: datetime | None = None,
) -> Document:
    """The report for a reader holding `permissions`: the proctoring signals and the people's
    side of the file (status, notes, decisions) appear only where those permissions allow."""
    sources = allowed_sources(permissions)
    sections = [
        executive_summary(data, sources),
        interview_metadata(data),
        questions_section(data),
        answers_section(data),
        skill_evaluation(data),
        technical_evaluation(data),
        coding_evaluation(data),
        communication(data),
        strengths(data),
        knowledge_gaps(data),
        follow_up_performance(data),
        transcript(data),
        timeline(data, sources),
    ]
    interview = data.interview
    return b.document(
        "interview",
        "Interview report",
        f"IV-{interview.number:04d} · {data.candidate.name} · {data.job.title}",
        sections,
        subject={
            "interview_id": str(interview.id),
            "candidate_id": str(data.candidate.id),
            "candidate_name": data.candidate.name,
            "job_title": data.job.title,
        },
        generated_at=generated_at,
    )
