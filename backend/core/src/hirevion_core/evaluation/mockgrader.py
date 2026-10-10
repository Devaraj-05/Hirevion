"""The mock profile's grader: deterministic answers for `evaluation.question` and
`evaluation.synthesis`, so CI evaluates interviews end to end and the eval gate runs without a
network.

It grades from the words (how many expected concepts the answer names, how long it is, how much
it hedges, whether it reasons and gives examples) and, like a model, it follows the prompt as
written. When the system message loses a clause the pipeline relies on (`registry.lint`), the
grader misbehaves the way a model would:

- without "character for character", its quotes are paraphrases, which verification drops;
- without the score anchors, its scores drift to the middle of the scale;
- without "data, not instructions", it obeys an instruction in the answer and scores it 10.

That is what lets the gate prove it blocks a regressed prompt (docs/evals, ADR-0031). A real
model's agreement is measured with `hv eval-interviews --live`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from hirevion_core.engine.analysis import heuristic
from hirevion_core.engine.faq import terms
from hirevion_core.engine.guardrails import mentions_manipulation, words
from hirevion_core.evaluation.registry import DIMENSIONS, has_clause

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_HEDGE = re.compile(
    r"\b(i think|i guess|maybe|probably|not (really )?sure|kind of|sort of|i believe)\b",
    re.IGNORECASE,
)
_REASON = re.compile(
    r"\b(because|so that|therefore|trade-?offs?|compared|instead|which means|since|otherwise)\b",
    re.IGNORECASE,
)
_EXAMPLE = re.compile(
    r"\b(in production|i measured|measured|for example|for instance|i (have|had|used|built|wrote)|"
    r"failed for me|under real load)\b|\d",
    re.IGNORECASE,
)
_PARAPHRASE = "the candidate explained that "
_MIDDLE = 5.0
_DRIFT = 0.35


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text.strip()) if s.strip()]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _names(sentence: str, concepts: Sequence[str]) -> bool:
    found = terms(sentence)
    for concept in concepts:
        wanted = terms(concept)
        if wanted and len(wanted & found) >= max(1, (len(wanted) + 1) // 2):
            return True
        if not wanted and concept.casefold() in sentence.casefold():
            return True
    return False


def _pick(options: Sequence[str], test: Any) -> list[str]:
    chosen = [s for s in options if test(s)][:2]
    return chosen or list(options[:1])


def _quote(sentence: str, verbatim: bool) -> str:
    return sentence if verbatim else _PARAPHRASE + sentence.lower()


def grade_question(system: str, request: Mapping[str, Any]) -> dict[str, Any]:
    """A reply for `QuestionReply`, from the system message and the request's data."""
    turns = request.get("answer_turns") or []
    raw = " ".join(str(turn.get("text", "")) for turn in turns)
    verbatim = has_clause(system, "verbatim")
    anchored = has_clause(system, "anchors")
    if mentions_manipulation(raw) and not has_clause(system, "data"):
        hijacked = next(s for s in sentences(raw) if mentions_manipulation(s))
        dimension = {"score": 10.0, "quotes": [_quote(hijacked, verbatim)], "rationale": ""}
        return {name: dict(dimension) for name in DIMENSIONS} | {
            "missing_concepts": [],
            "note": "The answer asked for full marks.",
        }
    own = [s for s in sentences(raw) if not mentions_manipulation(s)]
    answer = " ".join(own)
    concepts = [str(c) for c in request.get("expected_concepts") or []]
    question = str(request.get("question") or "")
    analysis = heuristic(question, answer, concepts, request.get("skill"))
    count = len(words(answer))
    coverage, correct, depth = analysis.completeness, analysis.correctness, analysis.depth
    hedges = len(_HEDGE.findall(answer))
    reasons, examples = len(_REASON.findall(answer)), len(_EXAMPLE.findall(answer))
    wanted = terms(question)
    overlap = len(wanted & terms(answer)) / len(wanted) if wanted else 0.0
    answered = count >= 3
    if analysis.off_topic:
        relevance = 0.1
    else:
        relevance = _clamp(0.2 + 0.8 * max(coverage, min(1.0, overlap * 2)))
    units = {
        "relevance": relevance if answered else 0.0,
        "correctness": correct,
        "completeness": coverage,
        "technical_depth": depth,
        "reasoning": _clamp(0.1 + 0.2 * reasons + 0.5 * coverage) if answered else 0.0,
        "clarity": _clamp(0.45 + 0.4 * min(1.0, count / 40) - 0.1 * hedges) if answered else 0.0,
        "communication": (
            _clamp(0.3 + 0.3 * min(1.0, len(own) / 3) + 0.3 * coverage - 0.1 * hedges)
            if answered
            else 0.0
        ),
        "evidence": _clamp(0.05 + 0.25 * examples + 0.4 * coverage) if answered else 0.0,
    }
    chosen = {
        "relevance": _pick(own, lambda s: _names(s, concepts) or bool(terms(s) & wanted)),
        "correctness": _pick(own, lambda s: _names(s, concepts)),
        "completeness": _pick(own, lambda s: _names(s, concepts)),
        "technical_depth": _pick(own, lambda s: bool(_REASON.search(s)) or _names(s, concepts)),
        "reasoning": _pick(own, lambda s: bool(_REASON.search(s))),
        "clarity": own[:1],
        "communication": own[:1],
        "evidence": _pick(own, lambda s: bool(_EXAMPLE.search(s))),
    }
    reply: dict[str, Any] = {}
    for name in DIMENSIONS:
        score = round(10 * units[name], 1)
        if not anchored:
            score = round(_MIDDLE + (score - _MIDDLE) * _DRIFT, 1)
        quotes = [_quote(s, verbatim) for s in chosen[name]] if answered else []
        reply[name] = {"score": score, "quotes": quotes, "rationale": ""}
    reply["missing_concepts"] = analysis.missing_concepts
    reply["note"] = (
        f"Names {len(concepts) - len(analysis.missing_concepts)} of {len(concepts)} expected "
        "concepts."
        if concepts
        else "No expected concepts were given."
    )
    return reply


def grade_synthesis(system: str, request: Mapping[str, Any]) -> dict[str, Any]:
    """A reply for `SynthesisReply`: findings from the strongest and weakest answers."""
    verbatim = True  # the synthesis prompt is not what the gate varies
    questions = list(request.get("questions") or [])

    def first_quote(question: Mapping[str, Any]) -> list[str]:
        raw = " ".join(str(t.get("text", "")) for t in question.get("answer_turns") or [])
        own = [s for s in sentences(raw) if not mentions_manipulation(s)]
        return [_quote(own[0], verbatim)] if own else []

    ranked = sorted(questions, key=lambda q: float(q.get("overall") or 0), reverse=True)
    strengths = [
        {
            "text": f"Answered the {q.get('skill') or 'general'} question soundly.",
            "skill": q.get("skill"),
            "quotes": first_quote(q),
        }
        for q in ranked
        if float(q.get("overall") or 0) >= 6.5
    ][:3]
    gaps = []
    for q in reversed(ranked):
        if float(q.get("overall") or 0) >= 6.0:
            continue
        missed = ", ".join(str(c) for c in (q.get("missing_concepts") or [])[:2])
        gaps.append(
            {
                "text": f"Missed {missed}." if missed else "Gave a thin answer.",
                "skill": q.get("skill"),
                "quotes": first_quote(q),
            }
        )
    follow = request.get("follow_ups") or {}
    followed = [q for q in questions if q.get("kind") == "follow_up"]
    summary = ""
    quotes: list[str] = []
    if follow.get("asked") and followed:
        summary = (
            f"Answered {follow['asked']} follow-up question(s), averaging {follow.get('mean')} "
            f"against {follow.get('main_mean')} on the main questions."
        )
        quotes = first_quote(followed[0])
    best = ranked[0] if ranked else {}
    return {
        "strengths": strengths[:5],
        "knowledge_gaps": gaps[:5],
        "follow_up_performance": {"summary": summary, "quotes": quotes},
        "communication": {
            "summary": "Explained their thinking in plain terms." if best else "",
            "quotes": first_quote(best) if best else [],
        },
    }
