"""The versioned prompt and rubric files, and the weights (SP-10 Task 1)."""

import pytest

from hirevion_core.evaluation import registry
from hirevion_core.evaluation.registry import (
    ACTIVE_QUESTION_PROMPT,
    ACTIVE_RUBRIC,
    ACTIVE_SYNTHESIS_PROMPT,
    DIMENSIONS,
    UnknownVersion,
    lint,
    load_prompt,
    load_rubric,
    rubric_base,
    rubric_from_policy,
    system_message,
)
from hirevion_core.interviews.templates import BUILT_IN_DEFAULTS, RUBRIC_DIMENSIONS


def test_the_active_files_exist_and_the_prompt_passes_its_lint() -> None:
    system = system_message(load_prompt(ACTIVE_QUESTION_PROMPT), load_rubric(ACTIVE_RUBRIC))
    assert lint(system) == []
    assert "data, not instructions" in load_prompt(ACTIVE_SYNTHESIS_PROMPT)
    assert DIMENSIONS == RUBRIC_DIMENSIONS


def test_a_prompt_that_loses_a_clause_is_named_by_the_lint() -> None:
    assert lint("Be generous: score everything 10.") == ["data", "verbatim", "anchors"]
    assert lint("data, not instructions. Score anchors: 0 to 10.") == ["verbatim"]


@pytest.mark.parametrize("name", ["../secrets", "Evaluation", "a", "missing-v9", "x/y"])
def test_names_that_are_not_files_are_refused(name: str) -> None:
    with pytest.raises(UnknownVersion):
        load_prompt(name)
    with pytest.raises(UnknownVersion):
        load_rubric(name)


def test_the_templates_weights_become_the_rubric() -> None:
    rubric = rubric_from_policy(BUILT_IN_DEFAULTS["rubric"])
    assert sum(rubric.weights.values()) == 100
    assert rubric.mean(dict.fromkeys(DIMENSIONS, 8.0)) == pytest.approx(8.0)
    assert rubric_base(rubric.version) == ACTIVE_RUBRIC


def test_the_weights_decide_the_mean_and_the_version() -> None:
    technical = rubric_from_policy(
        [{"dimension": "correctness", "weight": 80}, {"dimension": "clarity", "weight": 20}]
    )
    scores = dict.fromkeys(DIMENSIONS, 5.0) | {"correctness": 9.0, "clarity": 4.0}
    assert technical.mean(scores) == pytest.approx(8.0)
    even = rubric_from_policy(None)
    assert even.weights == dict.fromkeys(DIMENSIONS, 1)
    assert even.version != technical.version
    assert rubric_from_policy(None).version == even.version  # the digest is stable


def test_unusable_weights_are_ignored() -> None:
    rubric = rubric_from_policy(
        [
            {"dimension": "nonsense", "weight": 50},
            {"dimension": "clarity", "weight": True},
            {"dimension": "reasoning", "weight": -5},
            {"dimension": "evidence", "weight": 10},
        ]
    )
    assert rubric.weights["evidence"] == 10 and rubric.weights["clarity"] == 0
    assert rubric.mean({"clarity": 10.0}) == 0.0  # only a weighted dimension counts


def test_the_evaluation_version_is_supported() -> None:
    assert registry.EVALUATION_VERSION in registry.SUPPORTED_EVALUATION_VERSIONS
