"""Putting an uploaded document into a prompt. A resume or job description is wrapped in a tag
(`<resume>...</resume>`) that the prompt calls data, so text inside it must not be able to close
that tag and speak as the prompt."""

from __future__ import annotations

import re

_NAMES = (
    "resume",
    "job_description",
    "job",
    "candidate",
    "document",
    "skills",
    "experience_level",
    "template",
    "existing",
)
_TAGS = re.compile(rf"<(\s*/?\s*)({'|'.join(_NAMES)})\b", re.IGNORECASE)


def fence(text: str) -> str:
    """`text` with any of the prompt's own tags written so they are no longer tags."""
    return _TAGS.sub(r"&lt;\1\2", text)
