"""C7-2's exit criterion (master plan SP-15b): each third-eye signal's precision and recall on a
labelled set, and false positives per 45-minute session within budget. The set is synthetic
(seeded sessions with the detector's misses and false sightings modelled); real rooms need the
owner's labelled recordings (STATUS)."""

from __future__ import annotations

from hirevion_vision_agent.evaluation import (
    FP_BUDGET_ALL_PER_45_MIN,
    FP_BUDGET_PER_45_MIN,
    TARGET,
    Label,
    evaluate,
    match,
)
from hirevion_vision_agent.watch import KINDS


def test_every_signal_meets_its_target_and_false_positive_budget() -> None:
    report = evaluate(seed=2026)
    assert set(report) == set(KINDS)
    for kind, score in report.items():
        assert score.precision >= TARGET, (kind, score)
        assert score.recall >= TARGET, (kind, score)
        assert score.fp_per_45_min <= FP_BUDGET_PER_45_MIN, (kind, score)
    assert sum(s.fp_per_45_min for s in report.values()) <= FP_BUDGET_ALL_PER_45_MIN


def test_the_same_seed_gives_the_same_report() -> None:
    assert evaluate(seed=5, sessions=4, clean=2) == evaluate(seed=5, sessions=4, clean=2)


def test_an_episode_counts_once_for_the_label_it_overlaps() -> None:
    labels = [Label(10.0, 20.0), Label(100.0, 130.0)]
    # One started a moment early by a false sighting, one far from any, the second label missed.
    tp, fp, fn = match(labels, [(7.5, 19.0), (60.0, 64.0)], hold=2.0)
    assert (tp, fp, fn) == (1, 1, 1)


def test_a_label_shorter_than_the_hold_is_not_expected() -> None:
    tp, fp, fn = match([Label(10.0, 11.0)], [], hold=2.0)
    assert (tp, fp, fn) == (0, 0, 0)
