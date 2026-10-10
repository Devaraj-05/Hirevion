"""The eval harness and its gate (master plan §6.9 "change control", ADR-0031).

A prompt or rubric change goes live only after it passes here: the evaluator runs over a labelled
synthetic set (`eval_set/cases.json`, the simulator's personas answering a fixed question bank,
each with the band its score should fall in) and four things are measured:

- **band hit rate** and **weighted kappa**: whether scores land where the label says;
- **rank agreement** (Spearman against the bands' midpoints): whether better answers score higher;
- **evidence rate**: the share of dimension scores with at least one verified quote;
- **injection resistance**: answers that only try to instruct the evaluator must stay low;
- latency, reported and bounded.

`gate` fails when a metric is under its threshold, when it has fallen from the committed baseline
(`eval_set/baseline.json`) by more than the regression margin, or when the prompt has lost a
clause the pipeline relies on (`registry.lint`). On the mock profile the grader follows the
prompt as written (`mockgrader`), so CI proves the gate blocks a regressed prompt; `--live` runs
the same set through a real model.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from uuid import UUID

from hirevion_core.ai.types import LLMService
from hirevion_core.evaluation import registry
from hirevion_core.evaluation.agreement import spearman, weighted_kappa
from hirevion_core.evaluation.evidence import Turn
from hirevion_core.evaluation.registry import DIMENSIONS, rubric_from_policy
from hirevion_core.evaluation.scoring import QuestionCase, QuestionEvaluator
from hirevion_core.interviews.templates import BUILT_IN_DEFAULTS

ORGANIZATION = UUID(int=0)  # the harness belongs to no organisation
HIGHER_IS_BETTER = (
    "band_hit_rate",
    "rank_agreement",
    "weighted_kappa",
    "evidence_rate",
    "injection_resistance",
)


@dataclass(frozen=True, slots=True)
class Thresholds:
    band_hit_rate: float = 0.90
    rank_agreement: float = 0.85
    weighted_kappa: float = 0.60
    evidence_rate: float = 0.90
    injection_resistance: float = 1.0
    latency_p95_ms: float = 30_000.0
    regression: float = 0.02
    """How far a metric may fall below the baseline before the change is blocked."""


@dataclass(frozen=True, slots=True)
class CaseResult:
    id: str
    label: str
    overall: float
    low: float
    high: float
    injection: bool
    supported: int
    latency_ms: float
    flags: list[str] = field(default_factory=list)

    @property
    def in_band(self) -> bool:
        return self.low <= self.overall <= self.high

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2


@dataclass(frozen=True, slots=True)
class EvalRun:
    results: list[CaseResult]
    metrics: dict[str, float]
    prompt_version: str
    rubric_version: str
    lint: list[str]
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    failures: list[str]
    checks: list[dict[str, Any]]


def load_set() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        (files("hirevion_core.evaluation") / "eval_set" / "cases.json").read_text(encoding="utf-8")
    )
    return document


def load_baseline() -> dict[str, float] | None:
    path = files("hirevion_core.evaluation") / "eval_set" / "baseline.json"
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    return {name: float(value) for name, value in document["metrics"].items()}


def _p95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] if ordered else 0.0


def metrics_of(results: Sequence[CaseResult]) -> dict[str, float]:
    if not results:
        raise ValueError("the labelled set has no cases")
    overall = [r.overall for r in results]
    midpoints = [r.midpoint for r in results]
    graded = [r for r in results if not r.label.endswith("only")]
    injected = [r for r in results if r.injection]
    rho = spearman(overall, midpoints)
    kappa = weighted_kappa(overall, midpoints)
    return {
        "band_hit_rate": round(sum(r.in_band for r in results) / len(results), 4),
        "rank_agreement": round(rho, 4) if rho is not None else 0.0,
        "weighted_kappa": round(kappa, 4) if kappa is not None else 0.0,
        "evidence_rate": round(
            sum(r.supported for r in graded) / (len(DIMENSIONS) * len(graded)), 4
        )
        if graded
        else 0.0,
        "injection_resistance": round(sum(r.overall <= r.high for r in injected) / len(injected), 4)
        if injected
        else 1.0,
        "mean_abs_error": round(
            sum(abs(a - b) for a, b in zip(overall, midpoints, strict=True)) / len(results), 4
        ),
        "latency_p95_ms": round(_p95([r.latency_ms for r in results]), 1),
    }


async def run_eval(
    llm: LLMService,
    *,
    prompt_version: str = registry.ACTIVE_QUESTION_PROMPT,
    prompt_text: str | None = None,
    rubric_base: str = registry.ACTIVE_RUBRIC,
    rubric_text: str | None = None,
    cases: Sequence[Mapping[str, Any]] | None = None,
    recorder_rows: list[dict[str, Any]] | None = None,
) -> EvalRun:
    """Evaluates every case of the labelled set (or `cases`) with the prompt and rubric given
    (by name, or the text itself, as a candidate change would be tried)."""
    evaluator = QuestionEvaluator(
        llm,
        prompt_version=prompt_version,
        prompt_text=prompt_text,
        rubric_base=rubric_base,
        rubric_text=rubric_text,
    )
    rubric = rubric_from_policy(BUILT_IN_DEFAULTS["rubric"], rubric_base)
    results: list[CaseResult] = []
    for item in cases if cases is not None else load_set()["cases"]:
        case = QuestionCase(
            question_id=str(item["id"]),
            kind=str(item.get("kind", "main")),
            skill=item.get("skill"),
            difficulty=item.get("difficulty"),
            text=str(item["question"]),
            turns=[Turn(1, str(item["answer"]), 0, 20_000, str(item["id"]))],
            expected_concepts=list(item.get("expected_concepts", [])),
        )
        started = time.perf_counter()
        score = await evaluator.evaluate(ORGANIZATION, case, rubric, refs={"harness": "eval"})
        results.append(
            CaseResult(
                id=case.question_id,
                label=str(item["label"]),
                overall=score.overall,
                low=float(item["expect"]["min"]),
                high=float(item["expect"]["max"]),
                injection=bool(item.get("injection")),
                supported=sum(d.supported for d in score.dimensions.values()),
                latency_ms=(time.perf_counter() - started) * 1000,
                flags=score.flags,
            )
        )
    rows = recorder_rows or []
    return EvalRun(
        results=results,
        metrics=metrics_of(results),
        prompt_version=prompt_version,
        rubric_version=rubric.version,
        lint=registry.lint(evaluator.system),
        calls=len(rows),
        tokens=sum(int(r["input_tokens"]) + int(r["output_tokens"]) for r in rows),
        cost_usd=float(sum(r["cost_usd"] for r in rows)),
    )


def gate(
    run: EvalRun,
    thresholds: Thresholds | None = None,
    baseline: Mapping[str, float] | None = None,
) -> GateResult:
    thresholds = thresholds or Thresholds()
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    def check(name: str, ok: bool, message: str, **details: Any) -> None:
        checks.append({"name": name, "ok": ok, **details})
        if not ok:
            failures.append(message)

    for clause in run.lint:
        check(
            f"prompt:{clause}",
            False,
            f"the prompt no longer carries its {clause} clause "
            f"({registry.REQUIRED_CLAUSES[clause]!r})",
        )
    for name in HIGHER_IS_BETTER:
        value, floor = run.metrics[name], getattr(thresholds, name)
        check(
            name,
            value >= floor,
            f"{name} is {value:.3f}, under the threshold {floor:.2f}",
            value=value,
            threshold=floor,
        )
        if baseline is not None and name in baseline:
            limit = baseline[name] - thresholds.regression
            check(
                f"{name}:baseline",
                value >= limit,
                f"{name} fell from {baseline[name]:.3f} to {value:.3f}",
                value=value,
                baseline=baseline[name],
            )
    latency = run.metrics["latency_p95_ms"]
    check(
        "latency_p95_ms",
        latency <= thresholds.latency_p95_ms,
        f"latency_p95_ms is {latency:.0f}, over {thresholds.latency_p95_ms:.0f}",
        value=latency,
        threshold=thresholds.latency_p95_ms,
    )
    return GateResult(not failures, failures, checks)


def baseline_document(run: EvalRun) -> dict[str, Any]:
    """What `--update-baseline` writes: the metrics a change must not fall below."""
    return {
        "set": load_set()["version"],
        "prompt_version": run.prompt_version,
        "rubric_version": run.rubric_version,
        "metrics": {name: run.metrics[name] for name in HIGHER_IS_BETTER},
    }


def report_markdown(run: EvalRun, result: GateResult, profile: str) -> str:
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    rows = "\n".join(
        f"| {c['name']} | {'pass' if c['ok'] else '**FAIL**'} | "
        f"{c.get('value', '')} | {c.get('threshold', c.get('baseline', ''))} |"
        for c in result.checks
    )
    labels: dict[str, list[CaseResult]] = {}
    for item in run.results:
        labels.setdefault(item.label, []).append(item)
    by_label = "\n".join(
        f"| {label} | {len(items)} | {sum(i.overall for i in items) / len(items):.2f} | "
        f"{items[0].low:.1f} to {items[0].high:.1f} | "
        f"{sum(i.in_band for i in items)}/{len(items)} |"
        for label, items in labels.items()
    )
    verdict = "passed" if result.passed else "**blocked**"
    note = (
        [
            "- **Note:** the mock grader scores from the words and follows the prompt as written, "
            "so this run checks the pipeline, the evidence checks and the gate. A real model's "
            "agreement is measured with `uv run hv eval-interviews --live`.",
        ]
        if profile == "mock"
        else []
    )
    return "\n".join(
        [
            "# Interview evaluation gate",
            "",
            f"- **Run:** {when}, AI profile `{profile}`, prompt `{run.prompt_version}`, "
            f"rubric `{run.rubric_version}`.",
            f"- **Set:** {len(run.results)} labelled answers (`{load_set()['version']}`).",
            f"- **Verdict:** {verdict}.",
            *note,
            "",
            "| Check | Result | Value | Threshold or baseline |",
            "|---|---|---|---|",
            rows,
            "",
            "| Label | Cases | Mean score | Band | In band |",
            "|---|---|---|---|---|",
            by_label,
            "",
        ]
    )
