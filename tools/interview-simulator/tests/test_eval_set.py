"""The labelled set the evaluation gate uses is what the personas say (SP-10)."""

import json
from importlib.resources import files

from hirevion_interview_simulator.eval_set import BANDS, QUESTIONS, build_cases, document
from hirevion_interview_simulator.personas import INJECTIONS


def test_the_committed_set_is_what_the_personas_say() -> None:
    """If a persona changes, regenerate with `hirevion_interview_simulator.eval_set.write` and
    re-run the gate (`hv eval-interviews`)."""
    path = files("hirevion_core.evaluation") / "eval_set" / "cases.json"
    assert json.loads(path.read_text(encoding="utf-8")) == document()


def test_every_question_is_answered_by_every_kind_of_candidate() -> None:
    cases = build_cases()
    assert len(cases) == len(QUESTIONS) * len(BANDS)
    for label in BANDS:
        assert sum(1 for c in cases if c["label"] == label) == len(QUESTIONS)


def test_the_strong_cover_every_concept_and_the_injections_are_the_personas() -> None:
    cases = {c["id"]: c for c in build_cases()}
    strong = cases["strong-q1"]
    assert all(concept in strong["answer"] for concept in strong["expected_concepts"])
    assert cases["injection_only-q1"]["answer"] == INJECTIONS[0]
    assert cases["injection_with_answer-q1"]["answer"].startswith(INJECTIONS[0])
    assert cases["generic_paste-q1"]["answer"].startswith("The answer is to use best practices")
    assert cases["ai_text-q1"]["answer"].startswith("As an AI language model")
