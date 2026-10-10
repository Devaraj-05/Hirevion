"""Agreement statistics for calibration and the eval gate (SP-10 Task 4)."""

import math

import pytest

from hirevion_core.evaluation.agreement import spearman, summary, weighted_kappa


def test_spearman_uses_average_ranks_for_ties() -> None:
    assert spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 7]) == pytest.approx(8 / math.sqrt(95))
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_spearman_is_undefined_without_variation_or_pairs() -> None:
    assert spearman([1.0], [1.0]) is None
    assert spearman([3, 3, 3], [1, 2, 3]) is None
    assert spearman([], []) is None


def test_weighted_kappa_matches_a_hand_computed_case() -> None:
    # Observed disagreement 0.25; expected 1.25 (quadratic weights over three categories).
    assert weighted_kappa([0, 1, 2, 2], [0, 1, 1, 2], categories=3) == pytest.approx(0.8)


def test_weighted_kappa_is_one_for_identical_scores_and_negative_for_opposites() -> None:
    scores = [0.0, 2.5, 5.0, 7.5, 10.0, 6.0]
    assert weighted_kappa(scores, scores) == pytest.approx(1.0)
    assert weighted_kappa([0, 0, 10, 10], [10, 10, 0, 0]) < 0
    near = weighted_kappa(scores, [s + 1 if s < 10 else s for s in scores])
    assert near is not None and 0.9 < near < 1.0


def test_weighted_kappa_is_undefined_when_nobody_varies() -> None:
    assert weighted_kappa([5, 5, 5], [5, 5, 5]) is None
    assert weighted_kappa([], []) is None


def test_the_summary_collects_the_statistics() -> None:
    pairs = [(8.0, 8.0), (6.0, 7.0), (3.0, 2.0), (9.0, 6.0)]
    stats = summary(pairs)
    assert stats["n"] == 4
    assert stats["mean_abs_diff"] == pytest.approx(1.25)
    assert stats["within_one"] == pytest.approx(0.75)
    assert stats["spearman"] is not None and stats["weighted_kappa"] is not None
    assert summary([]) == {
        "n": 0,
        "spearman": None,
        "weighted_kappa": None,
        "mean_abs_diff": None,
        "within_one": None,
    }
