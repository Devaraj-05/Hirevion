"""Screening configuration (PRD §17): factor weights, knock-out flags and blind mode. A job uses
its own configuration if it has one, else the organisation's default, else the built-in one."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from hirevion_core.access import UNSET, Unset
from hirevion_core.access.actor import Actor
from hirevion_core.access.audit import record
from hirevion_core.access.errors import Invalid
from hirevion_core.models import ScreeningConfig

FACTORS = (
    "required_skills",
    "experience",
    "projects",
    "preferred_skills",
    "domain",
    "education",
    "location",
)
# PRD §17's example weights; location and work model only count when configured.
DEFAULT_WEIGHTS: dict[str, int] = {
    "required_skills": 35,
    "experience": 25,
    "projects": 15,
    "preferred_skills": 10,
    "domain": 10,
    "education": 5,
    "location": 0,
}
KNOCKOUTS = ("required_skills", "min_experience")
DEFAULT_KNOCKOUTS: dict[str, bool] = {"required_skills": True, "min_experience": True}


@dataclass(frozen=True, slots=True)
class Config:
    weights: dict[str, int]
    knockouts: dict[str, bool]
    blind: bool
    version: int
    """0 for the built-in configuration."""
    inherited: bool
    """Whether a job uses the organisation's (or the built-in) configuration."""
    source: str
    """`job`, `organization` or `default`."""


def _config(row: ScreeningConfig, *, inherited: bool) -> Config:
    return Config(
        {**DEFAULT_WEIGHTS, **row.weights},
        {**DEFAULT_KNOCKOUTS, **row.knockouts},
        row.blind,
        row.version,
        inherited,
        "organization" if row.job_id is None else "job",
    )


def built_in() -> Config:
    """The configuration of an organisation that never set one (a fresh copy each time)."""
    return Config(dict(DEFAULT_WEIGHTS), dict(DEFAULT_KNOCKOUTS), True, 0, True, "default")


def fingerprint(settings: Config) -> str:
    """What screening depends on in a configuration, as a hash. Versions restart when a job's own
    configuration is reset, so a result is reused by what the configuration says, not by its
    version."""
    content = {
        "weights": settings.weights,
        "knockouts": settings.knockouts,
        "blind": settings.blind,
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


async def _row(session: AsyncSession, job_id: UUID | None) -> ScreeningConfig | None:
    condition = (
        ScreeningConfig.job_id.is_(None) if job_id is None else ScreeningConfig.job_id == job_id
    )
    found: ScreeningConfig | None = await session.scalar(select(ScreeningConfig).where(condition))
    return found


async def effective(session: AsyncSession, job_id: UUID | None) -> Config:
    """The configuration that applies to `job_id` (None: the organisation's default)."""
    if job_id is not None:
        own = await _row(session, job_id)
        if own is not None:
            return _config(own, inherited=False)
    default = await _row(session, None)
    return _config(default, inherited=True) if default is not None else built_in()


def _weights(weights: dict[str, Any]) -> dict[str, int]:
    unknown = set(weights) - set(FACTORS)
    if unknown:
        raise Invalid(
            "unknown-factor", f"Unknown factors: {', '.join(sorted(unknown))}", field="weights"
        )
    cleaned: dict[str, int] = {}
    for factor in FACTORS:
        value = weights.get(factor, 0)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise Invalid("invalid-weight", "Use whole numbers from 0 to 100", field="weights")
        cleaned[factor] = value
    if sum(cleaned.values()) != 100:
        raise Invalid("weights-total", "The weights must add up to 100", field="weights")
    return cleaned


async def save(
    session: AsyncSession,
    actor: Actor,
    job_id: UUID | None,
    *,
    weights: dict[str, Any] | Unset = UNSET,
    knockouts: dict[str, bool] | Unset = UNSET,
    blind: bool | Unset = UNSET,
) -> Config:
    """Saves the organisation's default (`job_id` None) or a job's own configuration, which
    starts from what the job used until now. Saving nothing changes nothing, and makes no
    configuration of its own."""
    if all(isinstance(given, Unset) for given in (weights, knockouts, blind)):
        return await effective(session, job_id)
    row = await _row(session, job_id)
    created = row is None
    if row is None:
        start = await effective(session, job_id)
        row = ScreeningConfig(
            organization_id=actor.organization_id,
            job_id=job_id,
            weights=dict(start.weights),
            knockouts=dict(start.knockouts),
            blind=start.blind,
            version=0,
        )
        session.add(row)
    before = (dict(row.weights), dict(row.knockouts), row.blind)
    if not isinstance(weights, Unset):
        row.weights = _weights(weights)
    if not isinstance(knockouts, Unset):
        unknown = set(knockouts) - set(KNOCKOUTS)
        if unknown:
            raise Invalid("unknown-knockout", "Unknown knock-out rule", field="knockouts")
        row.knockouts = {**DEFAULT_KNOCKOUTS, **row.knockouts, **knockouts}
    if not isinstance(blind, Unset):
        row.blind = blind
    if not created and (row.weights, row.knockouts, row.blind) == before:
        return _config(row, inherited=False)  # nothing changed: no new version, no re-screening
    row.version += 1
    row.updated_by = actor.user_id
    await session.flush()
    await record(
        session,
        actor,
        "screening.config_changed",
        "job" if job_id else "organization",
        job_id or actor.organization_id,
        details={
            "version": row.version,
            "weights": row.weights,
            "knockouts": row.knockouts,
            "blind": row.blind,
        },
    )
    return _config(row, inherited=False)


async def reset(session: AsyncSession, actor: Actor, job_id: UUID) -> Config:
    """Drops a job's own configuration, so it uses the organisation's default again."""
    dropped = await _row(session, job_id)
    await session.execute(delete(ScreeningConfig).where(ScreeningConfig.job_id == job_id))
    await record(
        session,
        actor,
        "screening.config_reset",
        "job",
        job_id,
        details=(
            None
            if dropped is None
            else {
                "version": dropped.version,
                "weights": dropped.weights,
                "knockouts": dropped.knockouts,
                "blind": dropped.blind,
            }
        ),
    )
    return await effective(session, job_id)
