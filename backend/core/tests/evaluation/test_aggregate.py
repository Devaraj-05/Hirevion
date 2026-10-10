"""Skill and final evaluations, and the synthesis (SP-10 Task 3; PRD §70)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from hirevion_core.evaluation.aggregate import (
    SYNTHESIS_PURPOSE,
    SkillPlan,
    Synthesizer,
    aggregate,
)
from hirevion_core.evaluation.evidence import Evidence
from hirevion_core.evaluation.offline import offline_llm
from hirevion_core.evaluation.registry import DIMENSIONS, Rubric, rubric_from_policy
from hirevion_core.evaluation.scoring import DimensionScore, QuestionEvaluator, QuestionScore

from .factory import ORG, PARTIAL, STRONG, WEAK, make_case

EVEN = rubric_from_policy(None)
REFS = {"interview": "iv-1", "evaluation": "ev-1"}


def question(
    skill: str | None,
    overall: float,
    *,
    kind: str = "main",
    supported: bool = True,
    communication: float | None = None,
    qid: str | None = None,
) -> QuestionScore:
    evidence = [Evidence(f"{skill} quote", 1, 1000, 2000, "q")] if supported else []
    dims = {d: DimensionScore(overall, overall, supported, list(evidence), "") for d in DIMENSIONS}
    if communication is not None:
        dims["communication"] = DimensionScore(
            communication, communication, supported, list(evidence), ""
        )
    return QuestionScore(
        question_id=qid or f"{skill}-{overall}-{kind}",
        kind=kind,
        skill=skill,
        weight=1.0 if kind == "main" else 0.5,
        dimensions=dims,
        overall=overall,
        missing_concepts=[],
        note="",
        flags=[],
        model="m",
        input_digest="d",
        unsupported=[] if supported else list(DIMENSIONS),
    )


def test_skills_are_the_weighted_mean_of_their_questions_and_follow_ups_count_half() -> None:
    scores = [
        question("Python", 8.0),
        question("Python", 6.0, kind="follow_up"),
        question("PostgreSQL", 4.0),
    ]
    plan = [SkillPlan("Python", 60, True), SkillPlan("PostgreSQL", 40, True)]
    result = aggregate(scores, plan, EVEN)
    python, postgres = result.skills
    assert python.score == pytest.approx((8.0 * 1 + 6.0 * 0.5) / 1.5, abs=0.01)
    assert python.questions == 2 and postgres.score == 4.0
    assert result.overall == pytest.approx((60 * python.score + 40 * 4.0) / 100, abs=0.01)


def test_a_skill_with_no_scored_question_is_listed_not_scored_and_left_out_of_the_overall() -> None:
    plan = [SkillPlan("Python", 50, True), SkillPlan("Go", 50, True)]
    result = aggregate([question("Python", 7.0)], plan, EVEN)
    go = result.skills[1]
    assert go.score is None and go.questions == 0
    assert result.overall == 7.0
    assert "skill_not_assessed:Go" in result.flags


def test_skills_the_plan_did_not_name_still_count_with_a_default_weight() -> None:
    result = aggregate([question("Redis", 9.0), question(None, 5.0)], [], EVEN)
    assert [s.skill for s in result.skills] == ["Redis", "General"]
    assert result.overall == 7.0


def test_the_rubric_weights_flow_into_skill_scores() -> None:
    technical = Rubric(dict.fromkeys(DIMENSIONS, 0) | {"correctness": 100})
    dims = {d: DimensionScore(2.0, 2.0, True, [], "") for d in DIMENSIONS}
    dims["correctness"] = DimensionScore(10.0, 10.0, True, [], "")
    mixed = replace(question("Python", 3.0), dimensions=dims)
    plan = [SkillPlan("Python", 1, True)]
    assert aggregate([mixed], plan, technical).skills[0].score == 10.0
    assert aggregate([mixed], plan, EVEN).skills[0].score == pytest.approx((10 + 7 * 2) / 8)


def test_a_skill_without_a_single_supported_dimension_is_flagged() -> None:
    result = aggregate(
        [question("Python", 6.0, supported=False), question("Go", 6.0)],
        [SkillPlan("Python", 1, True), SkillPlan("Go", 1, False)],
        EVEN,
    )
    python, go = result.skills
    assert not python.supported and python.evidence == []
    assert go.supported and go.evidence[0].quote == "Go quote"
    assert "unsupported_skill:Python" in result.flags and "unsupported_skill:Go" not in result.flags


def test_communication_is_its_own_line_with_evidence() -> None:
    scores = [question("Python", 8.0, communication=9.0), question("Go", 6.0, communication=5.0)]
    result = aggregate(scores, [], EVEN)
    assert result.communication.score == 7.0
    assert result.communication.supported and result.communication.evidence


def test_the_coding_slot_is_left_for_sp16_and_nothing_scored_is_flagged() -> None:
    result = aggregate([], [SkillPlan("Python", 1, True)], EVEN)
    assert result.overall is None and result.communication.score is None
    assert result.coding == {"status": "pending", "score": None, "source": "sp-16"}
    assert "no_scored_answers" in result.flags


def test_follow_up_performance_compares_follow_ups_with_main_questions() -> None:
    scores = [question("Python", 8.0), question("Python", 6.0, kind="follow_up")]
    stats = aggregate(scores, [], EVEN).follow_ups
    assert stats == {"asked": 1, "mean": 6.0, "main_mean": 8.0, "delta": -2.0}
    assert aggregate([question("Python", 8.0)], [], EVEN).follow_ups["asked"] == 0


# The synthesis: one call, quotes verified against the interview's transcript.


async def scored(*cases: Any) -> list[QuestionScore]:
    llm, _ = offline_llm()
    evaluator = QuestionEvaluator(llm)
    return [await evaluator.evaluate(ORG, case, EVEN, refs=REFS) for case in cases]


async def test_the_synthesis_cites_verified_quotes_and_is_one_call() -> None:
    cases = [
        make_case(STRONG, question_id="q1"),
        make_case(WEAK, question_id="q2", skill="Python", text="What is a decorator?"),
    ]
    scores = await scored(*cases)
    llm, recorder = offline_llm()
    result = aggregate(scores, [], EVEN)
    synthesis = await Synthesizer(llm).synthesize(ORG, scores, cases, result, EVEN, refs=REFS)
    assert [r["purpose"] for r in recorder.rows] == [SYNTHESIS_PURPOSE]
    assert recorder.rows[0]["prompt_version"] == "evaluation-synthesis-v1"
    assert synthesis.strengths and synthesis.gaps
    for finding in [*synthesis.strengths, *synthesis.gaps]:
        assert finding.supported and finding.evidence
        assert all(item.seq >= 10 for item in finding.evidence)
    assert synthesis.communication.supported


async def test_a_strength_without_a_verified_quote_is_dropped_and_a_gap_is_flagged() -> None:
    cases = [make_case(PARTIAL)]
    scores = await scored(*cases)
    llm, _ = offline_llm()
    llm.scripted[SYNTHESIS_PURPOSE] = {
        "strengths": [
            {"text": "Great at sharding.", "skill": "PostgreSQL", "quotes": ["I sharded it"]},
            {
                "text": "Runs EXPLAIN ANALYZE.",
                "skill": "PostgreSQL",
                "quotes": ["run explain analyze"],
            },
        ],
        "knowledge_gaps": [
            {"text": "Never mentions statistics.", "skill": "PostgreSQL", "quotes": []},
        ],
        "follow_up_performance": {"summary": "None asked.", "quotes": []},
        "communication": {"summary": "Clear.", "quotes": ["look at the plan"]},
    }
    result = aggregate(scores, [], EVEN)
    synthesis = await Synthesizer(llm).synthesize(ORG, scores, cases, result, EVEN, refs=REFS)
    assert [s.text for s in synthesis.strengths] == ["Runs EXPLAIN ANALYZE."]
    [gap] = synthesis.gaps
    assert not gap.supported and gap.evidence == []
    assert synthesis.communication.supported


async def test_nothing_scored_means_no_call() -> None:
    llm, recorder = offline_llm()
    result = aggregate([], [], EVEN)
    synthesis = await Synthesizer(llm).synthesize(ORG, [], [], result, EVEN, refs=REFS)
    assert recorder.rows == [] and synthesis.strengths == [] and synthesis.model is None
