"""Seeding another interview reuses the library questions already there (the owner's run of
2026-11-21: 13 seeded interviews had left 13 copies of each question, and the interview asked
one of them ten times)."""

import asyncio
from typing import Any
from uuid import uuid4

from hirevion_interview_simulator.seed import LIBRARY, _coding_question, _library


class Conn:
    """Answers the lookup with `existing` and records every insert."""

    def __init__(self, existing: bool) -> None:
        self.existing = existing
        self.inserts: list[str] = []

    async def scalar(self, statement: Any, params: dict[str, Any]) -> Any:
        assert "SELECT" in str(statement)
        return uuid4() if self.existing else None

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        self.inserts.append(str(statement))


def test_the_library_is_seeded_once() -> None:
    questions = sum(len(rungs) for rungs in LIBRARY.values())
    fresh = Conn(existing=False)
    knowledge = asyncio.run(_library(fresh, uuid4()))
    assert len(fresh.inserts) == 2 * questions  # a question and its version each
    assert len(knowledge) == questions

    again = Conn(existing=True)
    assert asyncio.run(_library(again, uuid4())) == knowledge
    assert again.inserts == []


def test_the_coding_question_is_seeded_once() -> None:
    fresh = Conn(existing=False)
    asyncio.run(_coding_question(fresh, uuid4()))
    assert len(fresh.inserts) == 2

    again = Conn(existing=True)
    asyncio.run(_coding_question(again, uuid4()))
    assert again.inserts == []
