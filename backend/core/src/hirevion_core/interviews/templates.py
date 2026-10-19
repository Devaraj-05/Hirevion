"""Interview templates (PRD §21) with immutable versions (PRD §80): an edit writes the next
version, carrying over what didn't change, so an interview that pinned a version keeps it.
New templates start from the organisation's interview defaults. The skill matrix (master plan
§6.8 SkillMatrixBuilder) previews how a template's questions split across skills and
difficulties, and where the library is short."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Conflict, Invalid, NotFound
from hirevion_core.db.search import like_escape
from hirevion_core.interviews.questions import CODING_LANGUAGES, require_usable
from hirevion_core.jobs.taxonomy import resolve_skills
from hirevion_core.models import (
    InterviewTemplate,
    InterviewTemplateVersion,
    OrganizationSettings,
    Question,
    QuestionVersion,
)
from hirevion_core.models.interview_config import (
    DIFFICULTIES,
    PROCTORING_LEVELS,
    QUESTION_TYPES,
    THIRD_EYE_MODES,
)

# PRD §44's evaluation dimensions.
RUBRIC_DIMENSIONS = (
    "relevance",
    "correctness",
    "completeness",
    "technical_depth",
    "reasoning",
    "clarity",
    "communication",
    "evidence",
)
BUILT_IN_DEFAULTS: dict[str, Any] = {
    "duration_minutes": 45,
    "question_count": 10,
    "difficulty": {"easy": 20, "medium": 50, "hard": 30},
    "question_types": [
        "technical",
        "conceptual",
        "scenario",
        "problem_solving",
        "resume_based",
        "project_based",
    ],
    "use_resume": True,
    "use_jd": True,
    "adaptive_follow_ups": True,
    "coding": {"enabled": False, "languages": ["python"], "minutes": 20},
    "proctoring_level": "standard",
    "third_eye": "optional",
    "recording": {"screen": True, "camera": True, "audio": True},
    "rubric": [
        {"dimension": dimension, "weight": 13 if index < 4 else 12}
        for index, dimension in enumerate(RUBRIC_DIMENSIONS)
    ],
}
DEFAULT_KEYS = tuple(BUILT_IN_DEFAULTS)
# What each proctoring level turns on (SP-14 and SP-22 make these editable policies).
PROCTORING_PRESETS: dict[str, list[str]] = {
    "off": [],
    "basic": ["face", "focus"],
    "standard": ["face", "focus", "gaze", "phone", "processes", "displays"],
    "strict": ["face", "focus", "gaze", "phone", "processes", "displays", "audio", "third_eye"],
}


@dataclass(frozen=True, slots=True)
class TemplateFields:
    """What to set; None keeps the current value (or, for a new template, the default)."""

    name: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    question_count: int | None = None
    skills: Sequence[dict[str, Any]] | None = None
    difficulty: dict[str, int] | None = None
    question_types: Sequence[str] | None = None
    use_resume: bool | None = None
    use_jd: bool | None = None
    adaptive_follow_ups: bool | None = None
    coding: dict[str, Any] | None = None
    proctoring_level: str | None = None
    third_eye: str | None = None
    recording: dict[str, bool] | None = None
    rubric: Sequence[dict[str, Any]] | None = None
    questions: Sequence[tuple[UUID, int]] | None = None


@dataclass(frozen=True, slots=True)
class TemplateDetail:
    template: InterviewTemplate
    version: InterviewTemplateVersion


@dataclass(frozen=True, slots=True)
class MatrixRow:
    skill: str
    weight: int
    questions: int
    by_difficulty: dict[str, int]
    available: dict[str, int]
    gaps: dict[str, int] = field(default_factory=dict)


def allocate(total: int, shares: Sequence[int]) -> list[int]:
    """`total` split in proportion to `shares` (largest remainder; ties to the earlier)."""
    whole = sum(shares)
    if whole == 0 or total == 0:
        return [0 for _ in shares]
    exact = [total * share / whole for share in shares]
    counts = [math.floor(value) for value in exact]
    order = sorted(range(len(shares)), key=lambda i: (-(exact[i] - counts[i]), i))
    for index in order[: total - sum(counts)]:
        counts[index] += 1
    return counts


def _int(value: Any, low: int, high: int, code: str, message: str, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Invalid(code, message, field=where)
    return value


def _check_settings(values: dict[str, Any]) -> dict[str, Any]:
    """The settings every template version (and the defaults) must satisfy."""
    duration = _int(
        values["duration_minutes"],
        15,
        180,
        "invalid-duration",
        "Use 15 to 180 minutes",
        "duration_minutes",
    )
    count = _int(
        values["question_count"],
        1,
        50,
        "invalid-count",
        "Use 1 to 50 questions",
        "question_count",
    )
    difficulty = values["difficulty"]
    if set(difficulty) != set(DIFFICULTIES) or any(
        not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in difficulty.values()
    ):
        raise Invalid(
            "invalid-difficulty", "Give easy, medium and hard percentages", field="difficulty"
        )
    if sum(difficulty.values()) != 100:
        raise Invalid(
            "difficulty-total", "The difficulty mix must add up to 100", field="difficulty"
        )
    types = list(dict.fromkeys(values["question_types"]))
    if not types:
        raise Invalid("types-required", "Choose at least one question type", field="question_types")
    if any(t not in QUESTION_TYPES for t in types):
        raise Invalid("invalid-type", "Unknown question type", field="question_types")
    coding = values["coding"]
    languages = list(dict.fromkeys(str(lang).lower() for lang in coding.get("languages", [])))
    if any(lang not in CODING_LANGUAGES for lang in languages) or (
        coding.get("enabled") and not languages
    ):
        raise Invalid(
            "invalid-language", "Use Python, JavaScript, TypeScript or SQL", field="coding"
        )
    minutes = _int(
        coding.get("minutes", 20),
        5,
        90,
        "invalid-coding-minutes",
        "Use 5 to 90 minutes",
        "coding",
    )
    if coding.get("enabled") and minutes > duration:
        raise Invalid(
            "invalid-coding-minutes",
            "The coding time can't be longer than the interview",
            field="coding",
        )
    if values["proctoring_level"] not in PROCTORING_LEVELS:
        raise Invalid("invalid-proctoring", "Choose a proctoring level", field="proctoring_level")
    if values["third_eye"] not in THIRD_EYE_MODES:
        raise Invalid("invalid-third-eye", "Choose off, optional or required", field="third_eye")
    recording = {
        key: bool(values["recording"].get(key, True)) for key in ("screen", "camera", "audio")
    }
    rubric = []
    named = [item.get("dimension") for item in values["rubric"]]
    if len(set(named)) != len(named):
        raise Invalid("invalid-rubric", "Each rubric dimension can be listed once", field="rubric")
    for item in values["rubric"]:
        if item.get("dimension") not in RUBRIC_DIMENSIONS:
            raise Invalid("invalid-rubric", "Unknown rubric dimension", field="rubric")
        weight = _int(
            item.get("weight"), 0, 100, "invalid-rubric", "Use weights from 0 to 100", "rubric"
        )
        rubric.append({"dimension": item["dimension"], "weight": weight})
    if sum(item["weight"] for item in rubric) != 100:
        raise Invalid("rubric-total", "The rubric's weights must add up to 100", field="rubric")
    return {
        "duration_minutes": duration,
        "question_count": count,
        "difficulty": {key: difficulty[key] for key in DIFFICULTIES},
        "question_types": types,
        "use_resume": bool(values["use_resume"]),
        "use_jd": bool(values["use_jd"]),
        "adaptive_follow_ups": bool(values["adaptive_follow_ups"]),
        "coding": {
            "enabled": bool(coding.get("enabled")),
            "languages": languages or ["python"],
            "minutes": minutes,
        },
        "proctoring_level": values["proctoring_level"],
        "third_eye": values["third_eye"],
        "recording": recording,
        "rubric": rubric,
    }


async def _skills(session: AsyncSession, skills: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if not skills or len(skills) > 20:
        raise Invalid("skills-required", "Choose 1 to 20 skills", field="skills")
    names = [str(item.get("name", "")) for item in skills]
    resolved = await resolve_skills(session, names)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item, skill in zip(skills, resolved, strict=True):
        if skill is None:
            raise Invalid("skills-required", "Name each skill", field="skills")
        if skill.name.lower() in seen:
            raise Invalid("duplicate-skill", f"{skill.name} is listed twice", field="skills")
        seen.add(skill.name.lower())
        weight = _int(
            item.get("weight"), 1, 100, "invalid-weight", "Use weights from 1 to 100", "skills"
        )
        out.append(
            {
                "name": skill.name,
                "skill_id": str(skill.skill_id) if skill.skill_id else None,
                "weight": weight,
            }
        )
    if sum(item["weight"] for item in out) != 100:
        raise Invalid("skills-total", "The skill weights must add up to 100", field="skills")
    return out


async def interview_defaults(session: AsyncSession) -> dict[str, Any]:
    row = await session.scalar(select(OrganizationSettings))
    saved = row.interview_defaults if row else {}
    return {key: saved.get(key, BUILT_IN_DEFAULTS[key]) for key in DEFAULT_KEYS}


# Settings made of several parts: a change names the parts to change and leaves the rest.
NESTED = ("coding", "recording")


def _overlaid(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """`changes` over `base`; a nested setting is merged key by key (`recording` with only
    `audio` set leaves `screen` and `camera` as they were)."""
    merged = {**base, **changes}
    for key in NESTED:
        if isinstance(changes.get(key), dict) and isinstance(base.get(key), dict):
            merged[key] = {**base[key], **changes[key]}
    return merged


async def save_interview_defaults(
    session: AsyncSession, actor: Actor, changes: dict[str, Any]
) -> dict[str, Any]:
    unknown = set(changes) - set(DEFAULT_KEYS)
    if unknown:
        raise Invalid("unknown-setting", "Unknown interview default", field="interview_defaults")
    # The row is made if it isn't there (two first saves at once make one) and held for the save.
    await session.execute(
        pg_insert(OrganizationSettings)
        .values(organization_id=actor.organization_id)
        .on_conflict_do_nothing()
    )
    row = await session.scalar(
        select(OrganizationSettings).with_for_update().execution_options(populate_existing=True)
    )
    if row is None:  # the tenant's own row is always there once inserted
        raise NotFound("settings-not-found", "No settings for this organisation")
    saved = dict(row.interview_defaults or {})
    before = {key: saved.get(key, BUILT_IN_DEFAULTS[key]) for key in DEFAULT_KEYS}
    merged = _check_settings(_overlaid(before, changes))
    changed = {
        key: {"from": before[key], "to": merged[key]}
        for key in changes
        if merged[key] != before[key]
    }
    if not changed:
        return merged
    # Only what was set is stored: a built-in default that later changes still reaches an
    # organisation that never chose its own.
    row.interview_defaults = {**saved, **{key: merged[key] for key in changed}}
    row.updated_by = actor.user_id
    row.updated_at = func.now()
    await session.flush()
    await record(
        session,
        actor,
        "interview_defaults.changed",
        "organization",
        actor.organization_id,
        details={"changed": changed},
    )
    return merged


def _values(version: InterviewTemplateVersion) -> dict[str, Any]:
    return {key: getattr(version, key) for key in DEFAULT_KEYS}


async def _prepare(
    session: AsyncSession,
    base: dict[str, Any],
    base_skills: list[dict[str, Any]] | None,
    base_questions: list[dict[str, Any]],
    changes: TemplateFields,
) -> dict[str, Any]:
    """A version's checked contents: `changes` over `base`. Nothing is written."""
    given = {
        f.name: getattr(changes, f.name)
        for f in fields(changes)
        if getattr(changes, f.name) is not None
    }
    settings = _check_settings(
        _overlaid(base, {k: v for k, v in given.items() if k in DEFAULT_KEYS})
    )
    if changes.skills is not None:
        skills = await _skills(session, changes.skills)
    elif base_skills is not None:
        skills = base_skills
    else:
        raise Invalid("skills-required", "Choose 1 to 20 skills", field="skills")
    if changes.questions is not None:
        refs = list(dict.fromkeys(changes.questions))
        if len({q for q, _ in refs}) != len(refs):
            raise Invalid(
                "duplicate-question",
                "A question can be pinned once: choose one version of it",
                field="questions",
            )
        await require_usable(session, refs)
        pinned = [{"question_id": str(q), "version": v} for q, v in refs]
    else:
        pinned = base_questions
    if len(pinned) > settings["question_count"]:  # also when the count was lowered
        raise Invalid(
            "too-many-questions",
            "Pin no more questions than the template asks",
            field="questions",
        )
    return {**settings, "skills": skills, "questions": pinned}


async def _insert(
    session: AsyncSession,
    actor: Actor,
    template: InterviewTemplate,
    number: int,
    prepared: dict[str, Any],
) -> InterviewTemplateVersion:
    version = InterviewTemplateVersion(
        organization_id=template.organization_id,
        template_id=template.id,
        version=number,
        name=template.name,
        created_by=actor.user_id,
        **prepared,
    )
    session.add(version)
    await session.flush()
    return version


def _name(value: str | None) -> str:
    name = " ".join((value or "").split())
    if not name or len(name) > 200:
        raise Invalid("name-required", "Name the template (up to 200 characters)", field="name")
    return name


async def _named(session: AsyncSession, change: Callable[[], None]) -> None:
    """Applies `change` (adding or renaming a template) inside a savepoint, so a clashing name
    becomes a Conflict rather than an aborted transaction. The savepoint must open first:
    SQLAlchemy flushes pending changes when it does."""
    try:
        async with session.begin_nested():
            change()
            await session.flush()
    except IntegrityError as error:
        if "uq_interview_templates_organization_id_name" in str(error.orig):
            raise Conflict(
                "name-taken",
                "Another template, perhaps an archived one, has this name",
                field="name",
            ) from error
        raise


async def create_template(
    session: AsyncSession, actor: Actor, changes: TemplateFields
) -> TemplateDetail:
    template = InterviewTemplate(
        organization_id=actor.organization_id,
        name=_name(changes.name),
        description=(changes.description or "").strip()[:2000],
        status="active",
        current_version=1,
        created_by=actor.user_id,
    )
    prepared = await _prepare(session, await interview_defaults(session), None, [], changes)
    await _named(session, lambda: session.add(template))
    version = await _insert(session, actor, template, 1, prepared)
    await record(
        session,
        actor,
        "template.created",
        "interview_template",
        template.id,
        details={"name": template.name},
    )
    return TemplateDetail(template, version)


async def _template(
    session: AsyncSession, template_id: UUID, *, lock: bool = False
) -> InterviewTemplate:
    """The template; with `lock`, held until the transaction ends so two edits take turns."""
    template = await session.get(InterviewTemplate, template_id, with_for_update=lock)
    if template is None:
        raise NotFound("template-not-found", "No such template")
    return template


async def current(session: AsyncSession, template: InterviewTemplate) -> InterviewTemplateVersion:
    return await session.get_one(InterviewTemplateVersion, (template.id, template.current_version))


async def get_template(session: AsyncSession, template_id: UUID) -> TemplateDetail:
    template = await _template(session, template_id)
    return TemplateDetail(template, await current(session, template))


async def update_template(
    session: AsyncSession, actor: Actor, template_id: UUID, changes: TemplateFields
) -> TemplateDetail:
    """Writes the next version; the previous ones stay exactly as they were (PRD §80)."""
    template = await _template(session, template_id, lock=True)
    if template.status == "archived":
        raise Conflict("template-archived", "Restore the template before editing it")
    previous = await current(session, template)
    unchanged = {
        **_values(previous),
        "skills": list(previous.skills),
        "questions": list(previous.questions),
    }
    prepared = await _prepare(
        session, _values(previous), list(previous.skills), list(previous.questions), changes
    )
    renamed = changes.name is not None and _name(changes.name) != template.name
    if changes.name is not None:
        name = _name(changes.name)

        def rename() -> None:
            template.name = name

        await _named(session, rename)
    described = (
        changes.description is not None
        and changes.description.strip()[:2000] != template.description
    )
    if changes.description is not None:
        template.description = changes.description.strip()[:2000]
    if prepared == unchanged:
        # Nothing the interview is made of changed (a name or a description is the template's,
        # not a version's): no new version, so no copy of the last one.
        if renamed or described:
            await session.flush()
            await record(
                session,
                actor,
                "template.updated",
                "interview_template",
                template.id,
                details={"renamed": renamed, "described": described},
            )
        return TemplateDetail(template, previous)
    number = template.current_version + 1
    version = await _insert(session, actor, template, number, prepared)
    template.current_version = number
    await session.flush()
    await record(
        session,
        actor,
        "template.updated",
        "interview_template",
        template.id,
        details={"version": number},
    )
    return TemplateDetail(template, version)


async def set_archived(
    session: AsyncSession, actor: Actor, template_id: UUID, archived: bool
) -> InterviewTemplate:
    template = await _template(session, template_id)
    status = "archived" if archived else "active"
    if template.status != status:
        template.status = status
        await record(
            session,
            actor,
            "template.archived" if archived else "template.restored",
            "interview_template",
            template.id,
        )
    await session.flush()
    return template


async def list_versions(session: AsyncSession, template_id: UUID) -> list[InterviewTemplateVersion]:
    await _template(session, template_id)
    rows = await session.scalars(
        select(InterviewTemplateVersion)
        .where(InterviewTemplateVersion.template_id == template_id)
        .order_by(InterviewTemplateVersion.version)
    )
    return list(rows.all())


async def describe(
    session: AsyncSession, rows: Sequence[InterviewTemplate]
) -> list[TemplateDetail]:
    """Each template with its current version, in one query."""
    if not rows:
        return []
    versions = {
        version.template_id: version
        for version in (
            await session.scalars(
                select(InterviewTemplateVersion).where(
                    tuple_(
                        InterviewTemplateVersion.template_id, InterviewTemplateVersion.version
                    ).in_([(t.id, t.current_version) for t in rows])
                )
            )
        ).all()
    }
    return [TemplateDetail(template, versions[template.id]) for template in rows]


def templates_statement(status: str | None, query: str | None) -> Select[InterviewTemplate]:
    statement = select(InterviewTemplate).where(InterviewTemplate.status == (status or "active"))
    if query and query.strip():
        escaped = like_escape(query.strip())
        statement = statement.where(InterviewTemplate.name.ilike(f"%{escaped}%", escape="\\"))
    return statement


async def skill_matrix(session: AsyncSession, version: InterviewTemplateVersion) -> list[MatrixRow]:
    """Per skill: its share of the questions, split by the difficulty mix, against the approved
    library questions available for it."""
    names = [str(item["name"]) for item in version.skills]
    counts = allocate(version.question_count, [int(item["weight"]) for item in version.skills])
    current_version = (QuestionVersion.question_id == Question.id) & (
        QuestionVersion.version == Question.current_version
    )
    available: dict[tuple[str, str], int] = {
        (str(row[0]), str(row[1])): int(row[2])
        for row in await session.execute(
            select(func.lower(QuestionVersion.skill_name), QuestionVersion.difficulty, func.count())
            .select_from(Question)
            .join(QuestionVersion, current_version)
            .where(
                Question.status == "approved",
                QuestionVersion.type.in_(list(version.question_types or QUESTION_TYPES)),
                func.lower(QuestionVersion.skill_name).in_([n.lower() for n in names]),
            )
            .group_by(func.lower(QuestionVersion.skill_name), QuestionVersion.difficulty)
        )
    }
    rows = []
    for item, total in zip(version.skills, counts, strict=True):
        split = allocate(total, [version.difficulty[d] for d in DIFFICULTIES])
        by_difficulty = dict(zip(DIFFICULTIES, split, strict=True))
        have = {d: available.get((str(item["name"]).lower(), d), 0) for d in DIFFICULTIES}
        gaps = {d: by_difficulty[d] - have[d] for d in DIFFICULTIES if by_difficulty[d] > have[d]}
        rows.append(
            MatrixRow(str(item["name"]), int(item["weight"]), total, by_difficulty, have, gaps)
        )
    return rows
