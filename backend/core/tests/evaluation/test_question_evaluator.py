"""The async question evaluator: eight dimensions, each with verified evidence (SP-10 Task 2)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from hirevion_core.ai.types import AiUnavailable, ChatMessage
from hirevion_core.evaluation import registry
from hirevion_core.evaluation.offline import offline_llm
from hirevion_core.evaluation.registry import DIMENSIONS, Rubric, rubric_from_policy
from hirevion_core.evaluation.scoring import PURPOSE, UNSUPPORTED_CAP, QuestionEvaluator
from hirevion_core.interviews.templates import BUILT_IN_DEFAULTS

from .factory import INJECTION, ORG, PARTIAL, STRONG, WEAK, make_case

RUBRIC = rubric_from_policy(BUILT_IN_DEFAULTS["rubric"])
REFS = {"interview": "iv-1", "evaluation": "ev-1"}


def reply(score: float, quotes: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "score": score,
        "quotes": list(quotes),
        "rationale": "",
    }


def scripted(**changes: dict[str, Any]) -> dict[str, Any]:
    body = {dimension: reply(8.0, ["run EXPLAIN ANALYZE"]) for dimension in DIMENSIONS}
    body |= {"missing_concepts": [], "note": "ok"}
    return body | changes


async def test_each_dimension_is_scored_with_verified_timestamped_evidence() -> None:
    llm, _ = offline_llm()
    score = await QuestionEvaluator(llm).evaluate(ORG, make_case(STRONG), RUBRIC, refs=REFS)
    assert set(score.dimensions) == set(DIMENSIONS)
    for dimension in score.dimensions.values():
        assert dimension.supported and dimension.evidence
        for item in dimension.evidence:
            assert item.quote.lower() in STRONG.lower()
            assert item.seq == 10 and item.start_ms == 60_000 and item.end_ms == 68_000
    assert 7.0 <= score.overall <= 10.0
    assert score.unsupported == []


async def test_quotes_that_are_not_in_the_transcript_cap_the_score_and_flag_it() -> None:
    llm, _ = offline_llm()
    llm.scripted[PURPOSE] = scripted(
        correctness=reply(9.5, ["I would shard the database across three regions"]),
        clarity=reply(9.0, ["I would shard the database", "run EXPLAIN ANALYZE"]),
    )
    score = await QuestionEvaluator(llm).evaluate(ORG, make_case(STRONG), RUBRIC, refs=REFS)
    correctness = score.dimensions["correctness"]
    assert (correctness.raw_score, correctness.score) == (9.5, UNSUPPORTED_CAP)
    assert not correctness.supported and correctness.evidence == []
    clarity = score.dimensions["clarity"]  # one invented quote, one real one: it stands
    assert clarity.supported and clarity.score == 9.0
    assert [e.quote for e in clarity.evidence] == ["run EXPLAIN ANALYZE"]
    assert score.unsupported == ["correctness"]


async def test_a_low_score_without_quotes_is_flagged_but_not_raised() -> None:
    llm, _ = offline_llm()
    llm.scripted[PURPOSE] = scripted(completeness=reply(1.5))
    score = await QuestionEvaluator(llm).evaluate(ORG, make_case(STRONG), RUBRIC, refs=REFS)
    assert score.dimensions["completeness"].score == 1.5
    assert "completeness" in score.unsupported


async def test_quotes_must_come_from_this_questions_answer() -> None:
    llm, _ = offline_llm()
    llm.scripted[PURPOSE] = scripted(relevance=reply(9, ["Partitioning by month keeps it small"]))
    case = make_case(STRONG)
    score = await QuestionEvaluator(llm).evaluate(ORG, case, RUBRIC, refs=REFS)
    assert "relevance" in score.unsupported


async def test_the_rubric_weights_decide_the_questions_score() -> None:
    llm, _ = offline_llm()
    body = {d: reply(2.0, ["run EXPLAIN ANALYZE"]) for d in DIMENSIONS}
    body["correctness"] = reply(10.0, ["run EXPLAIN ANALYZE"])
    llm.scripted[PURPOSE] = {**body, "missing_concepts": [], "note": ""}
    evaluator = QuestionEvaluator(llm)
    only_correctness = Rubric(dict.fromkeys(DIMENSIONS, 0) | {"correctness": 100})
    even = rubric_from_policy(None)
    assert (
        await evaluator.evaluate(ORG, make_case(STRONG), only_correctness, refs=REFS)
    ).overall == 10
    assert (
        await evaluator.evaluate(ORG, make_case(STRONG), even, refs=REFS)
    ).overall == pytest.approx(3.0)


async def test_every_call_is_recorded_with_the_governance_fields() -> None:
    llm, recorder = offline_llm()
    await QuestionEvaluator(llm).evaluate(ORG, make_case(STRONG), RUBRIC, refs=REFS)
    [row] = recorder.rows
    assert row["purpose"] == PURPOSE and row["status"] == "ok"
    assert row["model"] == "mock-llm" and row["model_version"] == "mock-llm"
    assert row["prompt_version"] == registry.ACTIVE_QUESTION_PROMPT
    assert row["rubric_version"] == RUBRIC.version
    assert row["evaluation_version"] == registry.EVALUATION_VERSION
    assert row["input_refs"]["interview"] == "iv-1" and row["input_refs"]["question"] == "q1"
    assert len(row["input_refs"]["input_sha256"]) == 64
    assert row["output"]["relevance"]["score"] >= 0 and row["occurred_at"] is not None


async def test_the_request_is_data_with_no_identity_and_the_prompt_is_the_versioned_file() -> None:
    llm, _ = offline_llm()
    seen: list[Sequence[ChatMessage]] = []

    def spy(messages: Sequence[ChatMessage]) -> dict[str, Any]:
        seen.append(messages)
        return scripted()

    llm.scripted[PURPOSE] = spy
    case = make_case([WEAK, PARTIAL])
    await QuestionEvaluator(llm).evaluate(ORG, case, RUBRIC, refs=REFS)
    [system, user] = seen[0]
    assert system["role"] == "system" and user["role"] == "user"
    assert registry.load_prompt(registry.ACTIVE_QUESTION_PROMPT).strip() in system["content"]
    assert registry.load_rubric(registry.ACTIVE_RUBRIC).strip() in system["content"]
    data = json.loads(user["content"])
    assert [t["text"] for t in data["answer_turns"]] == [WEAK, PARTIAL]
    assert data["answer_turns"][0]["n"] == 10 and data["answer_turns"][0]["at"] == "00:01:00"
    assert set(data) == {
        "question",
        "kind",
        "skill",
        "difficulty",
        "expected_concepts",
        "question_rubric",
        "earlier_exchange",
        "answer_turns",
    }


async def test_an_injected_instruction_does_not_raise_the_score_and_is_flagged() -> None:
    llm, _ = offline_llm()
    evaluator = QuestionEvaluator(llm)
    plain = await evaluator.evaluate(ORG, make_case(PARTIAL), RUBRIC, refs=REFS)
    injected = await evaluator.evaluate(ORG, make_case(f"{INJECTION} {PARTIAL}"), RUBRIC, refs=REFS)
    assert injected.overall <= plain.overall + 0.01
    assert "manipulation_attempt" in injected.flags
    assert "manipulation_attempt" not in plain.flags
    only = await evaluator.evaluate(ORG, make_case(INJECTION), RUBRIC, refs=REFS)
    assert only.overall <= 2.0
    # The injected sentence is never cited as evidence for anything.
    cited = [e.quote for d in only.dimensions.values() for e in d.evidence]
    assert all("ignore your previous" not in q.lower() for q in cited)


async def test_late_answers_and_integrity_signals_travel_with_the_score() -> None:
    llm, _ = offline_llm()
    case = make_case(STRONG, late=True, flags=["ai_text_suspected"])
    score = await QuestionEvaluator(llm).evaluate(ORG, case, RUBRIC, refs=REFS)
    assert score.flags == ["ai_text_suspected", "late"]


async def test_the_bands_follow_the_answers_quality() -> None:
    llm, _ = offline_llm()
    evaluator = QuestionEvaluator(llm)
    strong = (await evaluator.evaluate(ORG, make_case(STRONG), RUBRIC, refs=REFS)).overall
    partial = (await evaluator.evaluate(ORG, make_case(PARTIAL), RUBRIC, refs=REFS)).overall
    weak = (await evaluator.evaluate(ORG, make_case(WEAK), RUBRIC, refs=REFS)).overall
    assert strong >= 7.0 > partial >= 3.5 > weak


async def test_the_missing_concepts_are_reported() -> None:
    llm, _ = offline_llm()
    score = await QuestionEvaluator(llm).evaluate(ORG, make_case(PARTIAL), RUBRIC, refs=REFS)
    assert "statistics" in score.missing_concepts


async def test_a_model_that_is_down_or_answers_nonsense_raises() -> None:
    llm, _ = offline_llm()
    llm.failures.append(AiUnavailable("down"))
    with pytest.raises(AiUnavailable):
        await QuestionEvaluator(llm).evaluate(ORG, make_case(), RUBRIC, refs=REFS)
    llm.scripted[PURPOSE] = {"relevance": "nope"}
    with pytest.raises(Exception, match=r"relevance|validation"):
        await QuestionEvaluator(llm).evaluate(ORG, make_case(), RUBRIC, refs=REFS)


async def test_a_version_can_be_pinned_by_name_and_a_prompt_overridden() -> None:
    llm, recorder = offline_llm()
    evaluator = QuestionEvaluator(llm, prompt_text="Score everything 10.", prompt_version="bad-v0")
    await evaluator.evaluate(ORG, make_case(), RUBRIC, refs=REFS)
    assert recorder.rows[0]["prompt_version"] == "bad-v0"
