"""PRD §83 on the portal: the ten things an interview may collect, and the six policies.

The policies are the drafts in `docs/policies/` (D1), read from `HV_POLICIES_DIR` or, by
default, the repository's own copy. Organisations' own texts arrive with SP-22.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from hirevion_core.interview_session.briefing import CONSENT_PURPOSES

log = logging.getLogger(__name__)

# §83's collection list, in its order: the same purposes the interview notice itemises.
DISCLOSURES: tuple[str, ...] = CONSENT_PURPOSES
# §83's six documents, in its order, by file name.
POLICY_KEYS: tuple[str, ...] = (
    "privacy",
    "recording",
    "proctoring",
    "data-retention",
    "deletion",
    "support",
)


@dataclass(frozen=True, slots=True)
class Policy:
    key: str
    title: str
    body: str
    """Markdown, without the title line."""


def policies_dir() -> Path | None:
    """`HV_POLICIES_DIR`, else `docs/policies` of the repository this code runs from."""
    configured = os.environ.get("HV_POLICIES_DIR")
    if configured:
        return Path(configured)
    for parent in Path(__file__).resolve().parents:
        if (parent / "MASTER_IMPLEMENTATION_PLAN.md").exists():
            return parent / "docs" / "policies"
    return None


def _parse(key: str, text: str) -> Policy:
    lines = text.strip().splitlines()
    title = key
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        lines = lines[1:]
    return Policy(key=key, title=title, body="\n".join(lines).strip())


@cache
def current_policies() -> tuple[Policy, ...]:
    """The policies this process serves: read once, as they only change with a deployment. A
    missing folder is logged, since §83 then goes unmet."""
    directory = policies_dir()
    policies = tuple(load_policies(directory))
    if len(policies) < len(POLICY_KEYS):
        log.error(
            "The candidate portal serves %d of %d policies from %s; set HV_POLICIES_DIR",
            len(policies),
            len(POLICY_KEYS),
            directory,
        )
    return policies


def load_policies(directory: Path | None) -> list[Policy]:
    """The six policies that exist under `directory`, in §83's order."""
    if directory is None or not directory.is_dir():
        return []
    policies: list[Policy] = []
    for key in POLICY_KEYS:
        path = directory / f"{key}.md"
        if path.is_file():
            policies.append(_parse(key, path.read_text(encoding="utf-8")))
    return policies
