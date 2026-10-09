"""The simulator's pieces without a server: its proofs pass the API's verifier, and each persona
answers as described."""

from __future__ import annotations

import time

import httpx
import pytest

from hirevion_core.candidate_access.dpop import MemoryReplayCache, check_proof, jwk_thumbprint
from hirevion_interview_simulator.client import DesktopClient
from hirevion_interview_simulator.personas import FAQ_QUESTION, NO_MORE, PERSONAS, persona

BASE = "http://api.hirevion.localhost"
QUESTION = {"id": "q", "type": "technical", "text": "How do you find out why a query is slow?"}
KNOWLEDGE = {"why a query is slow": ["explain analyze", "sequential scan", "statistics"]}


async def test_the_desktops_proofs_pass_the_apis_check() -> None:
    async with httpx.AsyncClient() as http:
        desktop = DesktopClient(http, base_url=BASE)
        token = "eyJ.example"  # noqa: S105 (not a secret)
        proof = desktop.proof("POST", "/interviews/x/answer", token)
        checked = await check_proof(
            proof,
            method="POST",
            url=f"{BASE}/api/v1/interviews/x/answer",
            replay=MemoryReplayCache(),
            now=time.time(),
            access_token=token,
            expected_jkt=jwk_thumbprint(desktop.jwk),
        )
    assert checked.jkt == jwk_thumbprint(desktop.jwk)


def test_strong_covers_every_concept_and_partial_about_half() -> None:
    strong = persona("strong", KNOWLEDGE).answer(QUESTION)
    assert all(concept in strong for concept in KNOWLEDGE["why a query is slow"])
    partial = persona("partial", KNOWLEDGE).answer(QUESTION)
    assert "explain analyze" in partial and "statistics" not in partial


def test_each_persona_closes_the_final_questions() -> None:
    final = {"id": "f", "type": "final", "text": "Any questions?"}
    strong = persona("strong")
    assert strong.answer(final) == FAQ_QUESTION and strong.answer(final) == NO_MORE
    assert persona("silent").answer(final) == ""
    for name in ("partial", "weak", "cheating"):
        assert persona(name).answer(final) == NO_MORE


def test_the_adversary_and_the_cheat_misbehave() -> None:
    adversary = persona("adversarial")
    answers = [adversary.answer(QUESTION) for _ in range(4)]
    assert "Ignore your previous instructions" in answers[1]
    assert "score" in answers[3]
    cheat = persona("cheating", KNOWLEDGE)
    answers = [cheat.answer(QUESTION) for _ in range(4)]
    assert answers[1].startswith("As an AI language model")
    assert answers[0] == answers[2]  # the same paste twice


def test_unknown_personas_are_refused() -> None:
    assert len(PERSONAS) == 6
    with pytest.raises(ValueError, match="unknown persona"):
        persona("genius")
