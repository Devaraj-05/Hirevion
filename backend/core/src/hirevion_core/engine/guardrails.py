"""Guardrails (master plan §6.8): what a candidate's words mean before any model sees them, and
what the AI may say.

`classify()` spots the requests the engine answers itself ("repeat", "I need a moment", "I don't
know", silence) and manipulation attempts: instructions aimed at the AI, or asking for scores or
answers. `safe_question()` is the output guard on model-written text: a short spoken question
with no markdown and nothing about scores, ratings or correct answers; anything else is replaced
by a template.
"""

from __future__ import annotations

import re
from typing import Literal

Intent = Literal["answer", "repeat", "moment", "dont_know", "silence", "manipulation", "no_more"]

SHORT_WORDS = 12
QUESTION_MAX = 400

_REPEAT = re.compile(
    r"\b(repeat|say (that|it|the question) again|pardon|come again|"
    r"did ?n[o']?t (catch|hear|get) (that|it|the question)|what was the question)\b",
    re.IGNORECASE,
)
_MOMENT = re.compile(
    r"\b(give me (a|one) (moment|minute|second|sec)|let me think|one (moment|minute|second)|"
    r"need a (moment|minute|second)|hold on|just a (moment|minute|second))\b",
    re.IGNORECASE,
)
_DONT_KNOW = re.compile(
    r"^\W*(i\s+(really\s+|honestly\s+)?(do\s*n[o']?t|dont)\s+know(\s+(that|this|the answer))?|"
    r"no idea|(i'?m\s+)?not sure|i\s+have\s+no\s+idea|pass|skip(\s+(this|it))?|"
    r"i\s+can'?t\s+answer\s+(that|this))\W*$",
    re.IGNORECASE,
)
_NO_MORE = re.compile(
    r"^\W*(no|nope|nothing|none|no questions?|not really|that'?s (all|it|everything)|"
    r"i'?m (good|fine|all set)|all good|no,? thanks?( you)?|nothing (else|more))\b",
    re.IGNORECASE,
)
_MANIPULATION = re.compile(
    "|".join(
        (
            r"ignore\s+(all\s+|any\s+)?(of\s+)?(the\s+|your\s+|my\s+)?(previous|prior|above|"
            r"earlier|system)\s+(instructions?|prompts?|rules?|messages?)",
            r"\bsystem\s+prompt\b",
            r"\byou\s+are\s+now\b",
            r"\bdeveloper\s+mode\b",
            r"\bjailbreak\b",
            r"\bpretend\s+(to\s+be|you\s+are)\b",
            r"\b(new|updated)\s+instructions?\b",
            r"\b(what('?s|\s+is)|tell\s+me|give\s+me|share)\s+(my|the)\s+(score|rating|grade|"
            r"marks?|result)",
            r"\bdid\s+i\s+(pass|fail|do\s+well|get\s+it\s+right)\b",
            r"\bam\s+i\s+(passing|doing\s+well|right)\b",
            r"\b(tell|give|show)\s+me\s+the\s+(correct\s+|right\s+|ideal\s+|model\s+)?"
            r"(answer|solution)",
            r"\bwhat('?s|\s+is)\s+the\s+(correct|right|ideal|expected)\s+answer\b",
            r"\b(mark|score|rate|grade)\s+(me|this|my\s+answer)\s+(as\s+)?(a\s+)?"
            r"(10|ten|full|perfect|highest|strong|excellent|pass)",
        )
    ),
    re.IGNORECASE,
)
_FORBIDDEN = re.compile(
    r"\b(score|scores|scored|scoring|rating|rated|grade|graded|marks|rubric|"
    r"correct answer|right answer|the answer is|you passed|you failed|"
    r"well done|excellent answer|perfect answer|wrong answer)\b|\d+\s*(%|/\s*10|out of)",
    re.IGNORECASE,
)
_MARKDOWN = re.compile(r"(\*\*|__|`|^\s*[-*#>]|\[[^\]]*\]\()", re.MULTILINE)


def words(text: str) -> list[str]:
    return re.findall(r"[\w'+#.-]+", text)


def classify(text: str, *, final_questions: bool = False) -> Intent:
    """What the candidate's words ask for. Requests are only recognised in short utterances, so
    an answer that happens to contain "let me think" is still an answer."""
    stripped = text.strip()
    if not stripped or not words(stripped):
        return "silence"
    if _MANIPULATION.search(stripped):
        return "manipulation"
    short = len(words(stripped)) <= SHORT_WORDS
    if final_questions and short and _NO_MORE.match(stripped):
        return "no_more"
    if short and _REPEAT.search(stripped):
        return "repeat"
    if short and _MOMENT.search(stripped):
        return "moment"
    if short and _DONT_KNOW.match(stripped):
        return "dont_know"
    return "answer"


def mentions_manipulation(text: str) -> bool:
    return bool(_MANIPULATION.search(text))


def safe_question(text: str | None) -> str | None:
    """`text` cleaned up when it is fit to say as a question, else None (use a template)."""
    if not text:
        return None
    cleaned = " ".join(text.split()).strip().strip('"').strip()
    if not 8 <= len(cleaned) <= QUESTION_MAX or not cleaned.endswith("?"):
        return None
    if _MARKDOWN.search(cleaned) or _FORBIDDEN.search(cleaned):
        return None
    if mentions_manipulation(cleaned):
        return None
    return cleaned


_AI_TELLS = re.compile(
    r"\b(as an ai(\s+language)?\s+model|as a large language model|i (cannot|can't) browse|"
    r"chatgpt|openai|my training data|knowledge cutoff|certainly!? here(?:'s| is))\b",
    re.IGNORECASE,
)


def fingerprint(text: str) -> str:
    """The answer with case, punctuation and spacing removed, to spot a repeated paste."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def integrity_flags(text: str, earlier: list[str]) -> list[str]:
    """Signals worth a reviewer's look, never a verdict: wording that reads as pasted from an
    AI tool, and an answer identical to an earlier one."""
    flags = []
    if _AI_TELLS.search(text):
        flags.append("ai_text_suspected")
    mark = fingerprint(text)
    if len(mark) >= 40 and mark in earlier:
        flags.append("repeated_answer")
    return flags
