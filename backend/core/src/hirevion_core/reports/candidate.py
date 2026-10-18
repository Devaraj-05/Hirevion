"""The internal candidate report (PRD §19, §20, §99): the whole file on one person, for the people
who decide. It holds scores, notes and recommendations, so it is confidential and never reaches
the candidate; what a candidate may see is `reports.visible`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from hirevion_core.models import Application, Job
from hirevion_core.reports import blocks as b
from hirevion_core.reports.blocks import Block, Document, Section
from hirevion_core.reports.candidate360 import Candidate360
from hirevion_core.reports.data import InterviewData
from hirevion_core.reports.labels import (
    HIRING_LABELS,
    RECOMMENDATION_LABELS,
    STATUS_LABELS,
)
from hirevion_core.reports.timeline import candidate_entries

SECTION_KEYS = (
    "profile",
    "applications",
    "screening",
    "interviews",
    "technical_skills",
    "coding",
    "proctoring",
    "hiring_input",
    "notes",
    "decision",
    "timeline",
)


def _profile(c360: Candidate360) -> Section:
    candidate = c360.detail.candidate
    profile: dict[str, Any] = candidate.profile or {}
    experience = profile.get("total_experience_years")
    summary = (profile.get("summary") or {}).get("value")
    content: list[Block] = [
        b.facts(
            [
                ("Name", candidate.name),
                ("Email", candidate.email),
                ("Phone", candidate.phone),
                ("Location", candidate.location),
                ("Headline", candidate.headline),
                ("Experience", f"{experience} years" if experience is not None else None),
            ]
        )
    ]
    if summary:
        content.append(b.text(str(summary)))
    return b.section("profile", "Profile", content)


def _applications(c360: Candidate360) -> Section:
    rows = []
    for application, job in c360.detail.applications:
        rows.append(
            [
                f"{job.title}",
                b.label(application.stage),
                HIRING_LABELS[application.hiring_status],
                str(application.rank) if application.rank is not None else None,
                b.day(application.created_at),
            ]
        )
    return b.section(
        "applications",
        "Applications",
        [b.table("Jobs applied to", ["Job", "Stage", "Hiring status", "Rank", "Applied"], rows)],
    )


def _screening(c360: Candidate360) -> Section:
    jobs = {application.id: job for application, job in c360.detail.applications}
    content: list[Block] = []
    for result in c360.screening:
        job: Job | None = jobs.get(result.application_id)
        content += [
            b.facts(
                [
                    ("Job", job.title if job else None),
                    ("Match score", f"{result.score} of 100"),
                    ("Screened", b.day(result.created_at)),
                ]
            ),
        ]
        if result.strengths:
            content += [b.text("Strengths"), b.bullets(result.strengths)]
        if result.concerns:
            content += [b.text("Concerns"), b.bullets(result.concerns)]
        if result.missing:
            content += [b.text("Missing"), b.bullets(result.missing)]
    return b.section(
        "screening",
        "Screening",
        content,
        note=None if content else "The candidate hasn't been screened yet.",
    )


def _interviews(c360: Candidate360) -> Section:
    rows = []
    for data in c360.interviews:
        view = data.scores
        rows.append(
            [
                f"IV-{data.interview.number:04d}",
                data.job.title,
                STATUS_LABELS.get(data.interview.status),
                b.day(data.interview.started_at, data.timezone),
                b.score(view.overall.value) if view else None,
                b.score(view.communication.value) if view else None,
                ", ".join(data.evaluation.flags)
                if data.evaluation and data.evaluation.flags
                else None,
            ]
        )
    return b.section(
        "interviews",
        "Interview history",
        [
            b.table(
                "Interviews",
                ["Interview", "Job", "Status", "Date", "Overall", "Communication", "Flags"],
                rows,
            )
        ],
        note=None if rows else "No interviews yet.",
    )


def _technical_skills(c360: Candidate360) -> Section:
    resume = {skill.name.casefold(): skill for skill in c360.detail.skills}
    interviewed: dict[str, list[str]] = {}
    for data in c360.interviews:
        if data.scores is None:
            continue
        for name, value in data.scores.skills.items():
            if value.value is not None:
                interviewed.setdefault(name, []).append(
                    f"IV-{data.interview.number:04d}: {b.score(value.value)}"
                )
    names = {skill.name for skill in c360.detail.skills} | set(interviewed)
    rows = []
    for name in sorted(names, key=str.casefold):
        skill = resume.get(name.casefold())
        years = (
            f"{float(skill.years):g} years"
            if skill is not None and skill.years is not None
            else None
        )
        rows.append(
            [
                name,
                "On the resume" + (f" ({years})" if years else "") if skill is not None else None,
                "; ".join(interviewed.get(name, [])) or None,
            ]
        )
    return b.section(
        "technical_skills",
        "Technical skills",
        [b.table("Skills claimed and skills shown", ["Skill", "Resume", "Interview"], rows)],
    )


def _coding(c360: Candidate360) -> Section:
    saved = sum(len(data.snapshots) for data in c360.interviews)
    return b.section(
        "coding",
        "Coding",
        [
            b.notice(
                "Code runs, test results and coding grades arrive with the coding service (SP-16)."
            ),
            b.facts([("Code snapshots saved", str(saved))]),
        ],
        pending=True,
    )


def _proctoring(c360: Candidate360) -> Section:
    if "proctoring" not in c360.sources:
        return b.section(
            "proctoring",
            "Proctoring",
            [
                b.notice(
                    "Proctoring results are shown only to people who may see proctoring reports."
                )
            ],
            note="Not shown to this reader.",
        )
    rows = []
    for data in c360.interviews:
        counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
        for event in data.events:
            counts[event.severity] = counts.get(event.severity, 0) + 1
        rows.append(
            [
                f"IV-{data.interview.number:04d}",
                str(counts["CRITICAL"]),
                str(counts["WARNING"]),
                str(counts["INFO"]),
                f"{len(data.reviews)} of {len(data.events)}",
            ]
        )
    return b.section(
        "proctoring",
        "Proctoring",
        [
            b.table(
                "Proctoring events by interview (signals for a reviewer, not a verdict)",
                ["Interview", "Critical", "Warnings", "Information", "Reviewed"],
                rows,
            )
        ],
        note=None if rows else "No interviews with proctoring yet.",
    )


def _hiring_input(c360: Candidate360) -> Section:
    rows = []
    for application, job in c360.detail.applications:
        for given in c360.hiring_inputs.get(application.id, []):
            rows.append(
                [
                    c360.people.get(given.author_id, "A hiring manager"),
                    job.title,
                    RECOMMENDATION_LABELS[given.recommendation],
                    ", ".join(f"{k.replace('_', ' ')} {v}/5" for k, v in given.ratings.items())
                    or None,
                    given.rationale,
                ]
            )
    return b.section(
        "hiring_input",
        "Hiring manager input",
        [b.table("Recommendations", ["From", "Job", "Recommendation", "Ratings", "Reasons"], rows)],
        note=None if rows else "No hiring manager has given input yet.",
    )


def _notes(c360: Candidate360) -> Section:
    rows = [
        [
            b.when(note.created_at),
            c360.people.get(note.author_id, "A reviewer"),
            b.clock(note.at_ms) if note.at_ms is not None else None,
            note.body,
        ]
        for note in c360.notes
    ]
    return b.section(
        "notes",
        "Recruiter notes",
        [b.table("Notes", ["When", "By", "Interview moment", "Note"], rows)],
        note=None if rows else "No notes yet.",
    )


def _decision(c360: Candidate360) -> Section:
    content: list[Block] = []
    applications: list[tuple[Application, Job]] = c360.detail.applications
    for application, job in applications:
        content.append(
            b.facts(
                [("Job", job.title), ("Hiring status", HIRING_LABELS[application.hiring_status])]
            )
        )
        rows = [
            [
                b.when(row.created_at),
                HIRING_LABELS[row.to_status],
                "Final decision"
                if row.decision
                else ("A person" if row.source == "user" else "System"),
                c360.people.get(row.actor_id) if row.actor_id else None,
                row.reason,
            ]
            for row in reversed(c360.history.get(application.id, []))
        ]
        content.append(b.table("Status changes", ["When", "Status", "How", "By", "Reason"], rows))
    return b.section("decision", "Decision and workflow", content)


async def _timeline(session: Any, c360: Candidate360) -> Section:
    entries = await candidate_entries(
        session,
        c360.detail.candidate.id,
        c360.application_ids,
        c360.interviews,
        c360.sources,
        min_severity="WARNING",
    )
    rows = [
        [b.when(entry.at), b.label(entry.source), entry.title, entry.detail] for entry in entries
    ]
    return b.section(
        "timeline",
        "Activity timeline",
        [b.table("What happened, oldest first", ["When", "Source", "What", "Detail"], rows)],
    )


async def candidate_report(
    session: Any, c360: Candidate360, *, generated_at: datetime | None = None
) -> Document:
    candidate = c360.detail.candidate
    sections = [
        _profile(c360),
        _applications(c360),
        _screening(c360),
        _interviews(c360),
        _technical_skills(c360),
        _coding(c360),
        _proctoring(c360),
        _hiring_input(c360),
        _notes(c360),
        _decision(c360),
        await _timeline(session, c360),
    ]
    return b.document(
        "candidate",
        "Candidate report",
        candidate.name,
        sections,
        subject={"candidate_id": str(candidate.id), "candidate_name": candidate.name},
        generated_at=generated_at,
    )


__all__ = ["SECTION_KEYS", "InterviewData", "candidate_report"]
