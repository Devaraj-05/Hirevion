"""Normalising and searching skills against the shared taxonomy (SP-04a Task 2)."""

import pytest

from hirevion_core.db.session import Database
from hirevion_core.jobs.taxonomy import normalise_skills, search_skills

pytestmark = pytest.mark.db


async def test_aliases_and_case_give_one_canonical_skill(app_db: Database) -> None:
    async with app_db.unscoped() as session:
        skills = await normalise_skills(session, ["JS", " javascript ", "py", "Go", "C++", "c#"])
    assert [(s.name, s.skill_id is not None) for s in skills] == [
        ("JavaScript", True),
        ("Python", True),
        ("Go", True),
        ("C++", True),
        ("C#", True),
    ]


async def test_unknown_skills_are_kept_as_written(app_db: Database) -> None:
    async with app_db.unscoped() as session:
        skills = await normalise_skills(session, ["Quantum basket weaving", "", "  "])
    assert [(s.name, s.skill_id) for s in skills] == [("Quantum basket weaving", None)]


async def test_search_finds_by_prefix_then_by_likeness(app_db: Database) -> None:
    async with app_db.unscoped() as session:
        first, *_ = await search_skills(session, "pyth")
        assert first.name == "Python"
        assert "Kubernetes" in [s.name for s in await search_skills(session, "k8s")]
        assert "PostgreSQL" in [s.name for s in await search_skills(session, "postgre")]
        assert await search_skills(session, "  ") == []
