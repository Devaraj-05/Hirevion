"""Blind screening (master plan §3.2(1)): the resume the AI assesses has no name, contact
details, links, address or personal-details section, and nothing that tells a reader the
candidate's gender, age, marital status, religion, caste or nationality. What's left is the work:
summary, skills, experience, projects, education.

This works by removing lines, so it errs towards removing: a line that names one of these things is
gone, whole. Resumes say them in many ways, so the rules are written as the ways resumes say
them ("Father's Name:", "Male, 28 years old", an address under its label, a PIN code after a
street) and each has a test; a way not yet seen is a new rule and a new test, never a reason to
send the line.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from hirevion_core.documents import pii
from hirevion_core.documents.sections import detect

# Bumped when the rules change, so results made under older (leakier) rules are not reused.
BLIND_VERSION = "blind-v2"

_APOSTROPHES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u2032": "'"})

# Labels that introduce a personal fact. Matched at the start of a line or of a `|`, `,`, `;`
# separated part of it, followed by a colon or dash: "Gender: Female", "Name: A | Age: 28".
_LABELS = (
    r"(?:father|mother|husband|spouse|wife|guardian|parent)'?s?(?:\s+name)?",
    r"marital(?:\s+status)?",
    r"gender",
    r"sex",
    r"age",
    r"religion",
    r"(?:sub[\s-]?)?caste",
    r"nationality",
    r"citizenship",
    r"blood\s+group",
    r"mother\s+tongue",
    r"date\s+of\s+birth",
    r"d\.?\s?o\.?\s?b\.?",
    r"birth\s*(?:date|place)",
    r"place\s+of\s+birth",
    r"aadhaar(?:\s+(?:no|number|card))?",
    r"pan\s+(?:no|number|card)",
    r"pan(?=\s*:)",
    r"passport(?:\s+(?:no|number))?",
    r"voter\s*id",
    r"driving\s+licen[cs]e(?:\s+(?:no|number))?",
    r"(?:permanent|current|present|residential|correspondence|home|local)?\s*address",
    r"pin\s*code",
)
_LABELLED = re.compile(
    r"(?:^|[|,;\u2022\u00b7])\s*(?:" + "|".join(_LABELS) + r")\s*[:\-\u2013\u2014]", re.IGNORECASE
)
_ADDRESS_LABEL = re.compile(
    r"(?:^|[|,;\u2022\u00b7])\s*(?:(?:permanent|current|present|residential|correspondence|home|local|postal|"
    r"mailing)\s+)?address\s*[:\-\u2013\u2014]\s*$",
    re.IGNORECASE,
)
# Things said without a label.
_STATED = re.compile(
    r"\b(?:male|female|transgender|non[\s-]binary)\b\W{0,3}\d{2}\s*(?:years?|yrs?)\b"
    r"|\b\d{2}\s*(?:years?|yrs?)\s+old\b"
    r"|\bcategory\s*[:\-\u2013\u2014]\s*(?:sc|st|obc|bc|mbc|sbc|ews|general|gen|nt)\b"
    r"|^\W*(?:male|female|transgender|non[\s-]binary|married|unmarried)\W*$",
    re.IGNORECASE,
)
# A street word with a PIN code at the end of the same line is an address. A six-digit number
# in the middle of a line ("processed 250000 records a day") is work, and so is "cross-functional".
_STREET = re.compile(
    r"\b(?:road|rd\.?|street|st\.|nagar|colony|layout|apartments?|apt\.?|flat|sector|lane|cross|"
    r"marg|house\s+no|h\.?\s?no\.?|block|phase|plot)\b(?!-).*\b[1-9]\d{2}\s?\d{3}\b(?:\W*india)?\W*$"
    r"|\bpin(?:\s*code)?\b\W*[1-9]\d{2}\s?\d{3}\b",
    re.IGNORECASE,
)
# A handle is a segment of its own ("Twitter: @jdoe", "mail | @jdoe"); "@Transactional" inside a
# sentence is a Java annotation.
_LINK = re.compile(
    r"https?://|www\.|linkedin\.com|github\.com|gitlab\.com|\.com/"
    r"|(?:^|[|,;\u2022\u00b7])\s*(?:linkedin|github|gitlab|twitter|facebook|instagram|behance|dribbble|"
    r"medium|portfolio|website|blog|leetcode|hackerrank|kaggle|stack\s*overflow)\b\s*[:\-/]"
    r"|(?:^|[|,;•·:])\s*@[A-Za-z0-9_.]{3,}\s*(?:[|,;•·]|$)"
    r"|\b[a-z0-9-]{3,}\.(?:dev|me|xyz|co\.in)\b"
    r"|^\W*[a-z0-9-]+\.(?:com|in|io|net|org)(?:/\S*)?\W*$",
    re.IGNORECASE,
)
# What is removed when pii finds it.
_CONTACT_KINDS = frozenset(
    {"email", "phone", "dob", "aadhaar", "pan", "vid", "passport", "voter_id", "bank_account"}
)
_TRIM = " .,;:()[]\"'"


def _name_patterns(names: Iterable[str]) -> list[re.Pattern[str]]:
    """What identifies the candidate in a line: their whole name (either order), and each part of
    three letters or more. A name of short parts ("Li Wu") is matched whole only."""
    patterns: list[re.Pattern[str]] = []
    for name in names:
        tokens = [token.strip(_TRIM) for token in re.split(r"[\s,]+", name.strip())]
        tokens = [token for token in tokens if token]
        if not tokens:
            continue
        for order in (tokens, tokens[::-1]):
            if len(order) > 1:
                joined = r"\W+".join(re.escape(token) for token in order)
                patterns.append(re.compile(rf"\b{joined}\b", re.IGNORECASE))
        patterns += [
            re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)
            for token in tokens
            if len(token) > 2
        ]
    return patterns


def _personal_blocks(text: str) -> list[tuple[int, int]]:
    """Where "Personal Details" and its like start and end: from the heading's own line to the
    first blank line after it, or the next heading the text uses, whichever comes first."""
    blocks = []
    for section in detect(text):
        if section.name != "personal":
            continue
        heading = text.rfind("\n", 0, section.start) + 1
        blank = text.find("\n\n", section.start)
        end = section.end if blank < 0 else min(section.end, blank)
        blocks.append((heading, end))
    return blocks


def blind_text(text: str, profile: dict[str, Any], extra_names: Iterable[str] = ()) -> str:
    text = text.translate(_APOSTROPHES)
    name_item = profile.get("name")
    names = [str(name_item["value"])] if isinstance(name_item, dict) else []
    patterns = _name_patterns([*names, *extra_names])
    contact_lines = {
        text.count("\n", 0, match.start) for match in pii.find(text) if match.kind in _CONTACT_KINDS
    }
    blocks = _personal_blocks(text)
    kept: list[str] = []
    position = 0
    address_lines = 0  # lines of an address that carry on below its label
    for number, line in enumerate(text.split("\n")):
        start, position = position, position + len(line) + 1
        if any(begin <= start < end for begin, end in blocks):
            continue
        if address_lines and line.strip() and ":" not in line:
            address_lines -= 1
            continue
        address_lines = 3 if _ADDRESS_LABEL.search(line) else 0
        if number in contact_lines or _LABELLED.search(line) or _STATED.search(line):
            continue
        if _STREET.search(line) or _LINK.search(line):
            continue
        if any(pattern.search(line) for pattern in patterns):
            continue
        kept.append(line)
    blind = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", blind).strip()
