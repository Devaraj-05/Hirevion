"""The plan prompt on the interview route's real model (C8-10): `uv run pytest --live
backend/core/tests/live -k plan` (a few cents). The owner's job: specific, distinct questions at
every level, most of them passing every check."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest

from hirevion_core.ai.openai_compat import OpenAICompatible
from hirevion_core.ai.prices import PriceBook
from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.settings import load_ai_settings
from hirevion_core.ai.types import AiContext
from hirevion_core.db.session import Database
from hirevion_core.ids import uuid7
from hirevion_core.interviews.plan import (
    SIMILARITY_PURPOSE,
    _ask,
    _ask_message,
    checked,
    distinct,
)

pytestmark = pytest.mark.live
MakeOrganization = Callable[[str], Awaitable[UUID]]

JOB = (
    "Title: Backend Engineer\nRequired skill: Python\nRequired skill: PostgreSQL\n"
    "Required skill: Redis\nResponsibility: Build FastAPI services for the payments ledger\n"
    "Responsibility: Keep reporting queries fast as data grows"
)
RESUME = (
    "Senior Backend Engineer Fintech Labs 2021 2026\nSkills: Python, PostgreSQL, Redis\n"
    "Project: Ledger service: Moved reporting queries to PostgreSQL read replicas and cut p95 "
    "by 60%"
)


async def test_nemotron_prepares_distinct_specific_questions(
    app_db: Database, make_organization: MakeOrganization
) -> None:
    settings = load_ai_settings()
    if not settings.nemotron_api_key.get_secret_value():
        pytest.skip("NEMOTRON_API_KEY is not set")
    llm = OpenAICompatible(settings, Recorder(app_db, PriceBook.load(), settings), "nemotron")
    org = await make_organization("LivePlan")
    counts = {"easy": 2, "medium": 3, "hard": 2}
    questions, _ = await _ask(
        llm, org, uuid7(), _ask_message(JOB, RESUME, "PostgreSQL", counts, []), "PostgreSQL"
    )
    kept = checked(
        questions,
        skill="PostgreSQL",
        counts=counts,
        resume=RESUME,
        taken_texts=set(),
        taken_concepts=set(),
    )
    assert len(kept) >= 6, [q.model_dump() for q in questions]
    assert {q.difficulty for q in kept} == {"easy", "medium", "hard"}
    assert not any(q.text.lower().startswith("what is postgresql") for q in kept)
    context = AiContext(organization_id=org, purpose=SIMILARITY_PURPOSE, prompt_version="live")
    vectors = (await llm.embed(context, [q.text for q in kept])).vectors
    assert len(distinct(["PostgreSQL"] * len(kept), vectors)) == len(kept)
