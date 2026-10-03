"""Blind screening (master plan §3.2(1)): the resume the AI assesses has no name, contact
details, links or personal-details section, and dates of birth are removed. What's left is the
work: summary, skills, experience, projects, education."""

from __future__ import annotations

import re
from typing import Any

from hirevion_core.documents import pii
from hirevion_core.documents.sections import detect

# Lines that describe the person rather than their work, wherever they appear.
_PERSONAL_LINE = re.compile(
    r"\b(?:father'?s?|mother'?s?|husband'?s?|spouse'?s?)\s+name\b|\bmarital\s+status\b|"
    r"\bgender\b|\breligion\b|\bcaste\b|\bnationality\b|\bdate\s+of\s+birth\b|\bd\.?o\.?b\b|"
    r"\baadhaar\b|\bpan\b\s*(?:no|number|:)|\bpassport\b|\bage\s*:",
    re.IGNORECASE,
)
_LINK = re.compile(r"https?://|www\.|linkedin\.com|github\.com|\.com/", re.IGNORECASE)


def blind_text(text: str, profile: dict[str, Any]) -> str:
    name_item = profile.get("name")
    name = str(name_item["value"]).strip() if isinstance(name_item, dict) else ""
    name_parts = [part for part in re.split(r"\s+", name) if len(part) > 2]
    contact_kinds = {"email", "phone", "dob", "aadhaar", "pan"}
    contact_lines = {
        text.count("\n", 0, match.start) for match in pii.find(text) if match.kind in contact_kinds
    }
    personal = [s for s in detect(text) if s.name == "personal"]
    kept: list[str] = []
    position = 0
    for number, line in enumerate(text.split("\n")):
        start, position = position, position + len(line) + 1
        if any(section.start - 40 <= start < section.end for section in personal):
            continue
        if number in contact_lines or _PERSONAL_LINE.search(line) or _LINK.search(line):
            continue
        if any(re.search(rf"\b{re.escape(part)}\b", line, re.IGNORECASE) for part in name_parts):
            continue
        kept.append(line)
    blind = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", blind).strip()
