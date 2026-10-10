"""Agreement between two scorers (the AI and a reviewer; the model and the labelled set).

Scores are on the 0 to 10 scale. `weighted_kappa` rounds them to whole points (eleven
categories) and weights a disagreement by its squared distance, so being a point off costs little
and being five off costs a lot; `spearman` compares the order, with ties ranked on average.
Both are undefined (None) when there is nothing to compare or nobody varies.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

CATEGORIES = 11  # whole points from 0 to 10


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        average = (start + end) / 2 + 1
        for position in range(start, end + 1):
            ranks[order[position]] = average
        start = end + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) != len(b):
        raise ValueError("the two scorers must have scored the same items")
    if len(a) < 2:
        return None
    ra, rb = _ranks(a), _ranks(b)
    mean_a, mean_b = sum(ra) / len(ra), sum(rb) / len(rb)
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb, strict=True))
    spread_a = sum((x - mean_a) ** 2 for x in ra)
    spread_b = sum((y - mean_b) ** 2 for y in rb)
    if spread_a == 0 or spread_b == 0:
        return None
    return covariance / math.sqrt(spread_a * spread_b)


def weighted_kappa(
    a: Sequence[float], b: Sequence[float], *, categories: int = CATEGORIES
) -> float | None:
    """Cohen's kappa with quadratic weights over `categories` whole-point categories."""
    if len(a) != len(b):
        raise ValueError("the two scorers must have scored the same items")
    count = len(a)
    if count == 0 or categories < 2:
        return None
    top = categories - 1

    def bucket(value: float) -> int:
        return min(top, max(0, round(value)))

    observed = [[0.0] * categories for _ in range(categories)]
    rows, columns = [0.0] * categories, [0.0] * categories
    for x, y in zip(a, b, strict=True):
        i, j = bucket(x), bucket(y)
        observed[i][j] += 1
        rows[i] += 1
        columns[j] += 1
    disagreement = expected = 0.0
    for i in range(categories):
        for j in range(categories):
            weight = (i - j) ** 2 / top**2
            disagreement += weight * observed[i][j]
            expected += weight * rows[i] * columns[j] / count
    if expected == 0:
        return None
    return 1 - disagreement / expected


def summary(pairs: Sequence[tuple[float, float]]) -> dict[str, Any]:
    """The statistics over (first scorer, second scorer) pairs."""
    first = [p[0] for p in pairs]
    second = [p[1] for p in pairs]
    if not pairs:
        return {
            "n": 0,
            "spearman": None,
            "weighted_kappa": None,
            "mean_abs_diff": None,
            "within_one": None,
        }
    differences = [abs(x - y) for x, y in pairs]
    rho, kappa = spearman(first, second), weighted_kappa(first, second)
    return {
        "n": len(pairs),
        "spearman": round(rho, 4) if rho is not None else None,
        "weighted_kappa": round(kappa, 4) if kappa is not None else None,
        "mean_abs_diff": round(sum(differences) / len(differences), 4),
        "within_one": round(sum(1 for d in differences if d <= 1.0) / len(differences), 4),
    }
