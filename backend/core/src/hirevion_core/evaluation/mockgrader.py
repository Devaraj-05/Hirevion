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


# The coding question (SP-16, ADR-0033): the code is read from its shape, never run.

CODING_CRITERIA = (
    "correctness",
    "approach",
    "edge_cases",
    "time_complexity",
    "space_complexity",
    "code_quality",
    "readability",
)
_CODE_COMMENT = re.compile(r"^\s*(#|//|--|/\*|\*)")
_CODE_DEF = re.compile(
    r"^\s*(async\s+)?(def|function|class)\s|^\s*(export\s+)?(const|let)\s+\w+\s*=\s*"
    r"(async\s*)?\(|^\s*export\s+(async\s+)?function\s|^\s*(SELECT|WITH)\b",
    re.IGNORECASE,
)
_CODE_RETURN = re.compile(r"\breturn\b|^\s*SELECT\b", re.IGNORECASE)
_CODE_LOOP = re.compile(
    r"^\s*(for|while)\b|\bfor\s*\(|\.(forEach|map|filter|reduce)\(|\bFROM\b", re.IGNORECASE
)
_CODE_HASH = re.compile(
    r"=\s*\{\s*\}|\bdict\(|\bset\(|\bnew\s+(Map|Set)\b|\b(Map|Set)<|\bCounter\(|defaultdict|"
    r"\.has\(|\bin\s+seen\b|\bGROUP\s+BY\b|\bJOIN\b",
    re.IGNORECASE,
)
_CODE_EDGE = re.compile(
    r"\bif\s+not\b|\bis\s+None\b|===?\s*(null|undefined)\b|\.length\s*(===?|<=?)\s*[012]\b|"
    r"\blen\([^)]*\)\s*(==|<=?)\s*[012]\b|\braise\b|\bthrow\b|\bCOALESCE\b|\bIS\s+NULL\b|"
    r"\bHAVING\b",
    re.IGNORECASE,
)
_CODE_UNSAFE = re.compile(r"\beval\(|\bexec\(|^\s*except\s*:|catch\s*\(\w*\)\s*\{\s*\}")
_CODE_NAME = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_CODE_KEYWORDS = frozenset(
    [
        "def",
        "return",
        "if",
        "not",
        "or",
        "and",
        "in",
        "for",
        "while",
        "is",
        "none",
        "true",
        "false",
        "else",
        "elif",
        "import",
        "from",
        "class",
        "function",
        "const",
        "let",
        "var",
        "new",
        "async",
        "await",
        "export",
        "null",
        "undefined",
        "this",
        "of",
        "typeof",
        "select",
        "where",
        "group",
        "by",
        "order",
        "having",
        "join",
        "on",
        "as",
        "count",
        "sum",
        "min",
        "max",
        "desc",
        "asc",
        "limit",
        "with",
    ]
)
_LOOP_NAMES = frozenset("ijknxy_")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _code_quotes(
    lines: Sequence[str], test: Any, fallback: Sequence[str], verbatim: bool
) -> list[str]:
    chosen = [line.strip() for line in lines if test(line)][:2]
    chosen = chosen or [line.strip() for line in fallback[:1]]
    return [_quote(line, verbatim) for line in chosen]


def _code_units(own: Sequence[str], code: Sequence[str]) -> tuple[dict[str, float], dict[str, Any]]:
    """Each criterion's grade from 0 to 1, and what the code was seen to do."""
    comments = len(own) - len(code)
    entry = any(_CODE_DEF.search(line) for line in code)
    returns = any(_CODE_RETURN.search(line) for line in code)
    loops = [line for line in code if _CODE_LOOP.search(line)]
    nested = any(
        _indent(later) > _indent(first)
        for index, first in enumerate(loops)
        for later in loops[index + 1 :]
    )
    hashed = any(_CODE_HASH.search(line) for line in code)
    edges = sum(len(_CODE_EDGE.findall(line)) for line in code)
    iterates = bool(loops)
    names = [
        name
        for line in code
        for name in _CODE_NAME.findall(line)
        if name.lower() not in _CODE_KEYWORDS and name not in _LOOP_NAMES
    ]
    good_names = bool(names) and sum(len(n) >= 3 for n in names) / len(names) >= 0.6
    tidy = all(len(line) <= 100 for line in code)
    unsafe = any(_CODE_UNSAFE.search(line) for line in code)
    # Code that never touches the input isn't an attempt, however tidy it looks.
    attempt = 1.0 if iterates or hashed else 0.6
    units = {
        "correctness": 0.15 * entry
        + 0.15 * returns
        + 0.35 * iterates
        + 0.2 * (hashed or nested)
        + 0.15 * min(1.0, edges / 2),
        "approach": 0.2 + (0.6 if hashed else 0.3 if iterates else 0.0) + 0.2 * (comments > 0),
        "edge_cases": (0.15 if iterates or hashed else 0.05) + 0.35 * edges,
        "time_complexity": 0.4 if nested else 0.9 if iterates else 0.3,
        "space_complexity": 0.8 if hashed or iterates else 0.3,
        "code_quality": attempt
        * (0.35 + 0.2 * (comments > 0) + 0.2 * good_names + 0.15 * tidy + 0.1 * entry)
        - 0.3 * unsafe,
        "readability": attempt * (0.3 + 0.3 * good_names + 0.25 * (comments > 0) + 0.15 * tidy),
    }
    seen = {"nested": nested, "iterates": iterates, "hashed": hashed, "edges": edges}
    return units, seen


def grade_coding(system: str, request: Mapping[str, Any]) -> dict[str, Any]:
    """A reply for `CodingReply`, from the system message and the request's code."""
    verbatim = has_clause(system, "verbatim")
    anchored = has_clause(system, "anchors")
    lines = [line for line in str(request.get("code") or "").splitlines() if line.strip()]
    hijack = [line for line in lines if mentions_manipulation(line)]
    reply: dict[str, Any]
    if hijack and not has_clause(system, "data"):
        top = {"score": 10.0, "quotes": [_quote(hijack[0].strip(), verbatim)], "rationale": ""}
        reply = {name: dict(top) for name in CODING_CRITERIA}
        reply["time_complexity"]["estimate"] = "O(1)"
        reply["space_complexity"]["estimate"] = "O(1)"
        return reply | {"edge_cases_missed": [], "summary": "The code asked for full marks."}
    own = [line for line in lines if not mentions_manipulation(line)]
    code = [line for line in own if not _CODE_COMMENT.match(line)]
    if not code:
        quotes = [_quote(own[0].strip(), verbatim)] if own else []
        reply = {
            name: {"score": 0.0, "quotes": list(quotes), "rationale": ""}
            for name in CODING_CRITERIA
        }
        reply["time_complexity"]["estimate"] = ""
        reply["space_complexity"]["estimate"] = ""
        return reply | {"edge_cases_missed": [], "summary": "There is no code, only comments."}
    units, seen = _code_units(own, code)
    defs = [line for line in code if _CODE_DEF.search(line)] or list(code)
    picks = {
        "correctness": (code, _CODE_RETURN.search),
        "approach": (code, lambda s: _CODE_HASH.search(s) or _CODE_LOOP.search(s)),
        "edge_cases": (code, _CODE_EDGE.search),
        "time_complexity": (code, _CODE_LOOP.search),
        "space_complexity": (code, _CODE_HASH.search),
        "code_quality": (defs, bool),
        "readability": (own, _CODE_COMMENT.match),
    }
    reply = {}
    for name in CODING_CRITERIA:
        score = round(10 * _clamp(units[name]), 1)
        if not anchored:
            score = round(_MIDDLE + (score - _MIDDLE) * _DRIFT, 1)
        where, test = picks[name]
        quotes = _code_quotes(where, test, defs, verbatim)
        reply[name] = {"score": score, "quotes": quotes, "rationale": ""}
    nested, iterates, hashed = seen["nested"], seen["iterates"], seen["hashed"]
    time = "O(n^2)" if nested else "O(n)" if iterates else "O(1)"
    reply["time_complexity"]["estimate"] = time
    reply["space_complexity"]["estimate"] = "O(n)" if hashed else "O(1)"
    method = (
        "a hash lookup"
        if hashed
        else "nested loops"
        if nested
        else "a loop"
        if iterates
        else "no iteration"
    )
    reply["edge_cases_missed"] = [] if seen["edges"] else ["empty input"]
    reply["summary"] = f"Uses {method}; estimated {time} time."
    return reply
