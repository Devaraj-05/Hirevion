"""The spellings of one skill, from the taxonomy's data file, for checking that a quote is about
the skill an AI named: "py" is supported by a quote that says "Python"."""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from importlib.resources import files

import yaml

_SKILLS_FILE = files("hirevion_core.jobs") / "data" / "skills.yaml"


def fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


@lru_cache(maxsize=1)
def _groups() -> dict[str, frozenset[str]]:
    """Each folded name or alias, to every folded spelling of its skill."""
    entries = yaml.safe_load(_SKILLS_FILE.read_text(encoding="utf-8"))
    out: dict[str, frozenset[str]] = {}
    for name, _category, aliases in entries:
        spellings = frozenset(fold(spelling) for spelling in [name, *aliases])
        for spelling in spellings:
            out[spelling] = out.get(spelling, frozenset()) | spellings
    return out


def related_terms(value: str) -> frozenset[str]:
    """Every spelling of the skill `value` names, or nothing when the taxonomy doesn't know it."""
    return _groups().get(fold(value).strip(" .,;:()[]"), frozenset())
