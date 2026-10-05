"""The screening evaluation's measures (SP-05 Task 7)."""

import pytest

from hirevion_devcli.screening_eval import job_skill_sets, label, ndcg_at, precision_at


def test_a_perfect_ranking_scores_one_and_a_reversed_one_less() -> None:
    labels = [1.0, 2 / 3, 1 / 3, 0.0]
    assert ndcg_at(labels) == pytest.approx(1.0)
    assert ndcg_at(list(reversed(labels))) < 0.7
    assert ndcg_at([0.0, 0.0]) == 1.0  # nothing relevant to find


def test_precision_counts_the_relevant_in_the_top() -> None:
    assert precision_at([1.0, 2 / 3, 0.0, 1 / 3], k=4) == 0.5
    assert precision_at([], k=10) == 0.0


def test_labels_are_the_share_of_the_jobs_skills() -> None:
    assert label(["Python", "Go"], ["python", "Kubernetes", "Go"]) == pytest.approx(2 / 3)


def test_jobs_are_built_from_the_role_families() -> None:
    assert job_skill_sets() == [
        ["Python", "Django", "PostgreSQL"],
        ["JavaScript", "TypeScript", "React"],
        ["SQL", "Python", "Apache Spark"],
    ]
