"""`hv trace` (H0): checks the PRD traceability checklist, Appendix A of the master plan.

Every row must say where its section is delivered: a sub-project (`SP-nn`), a plan section
(`§n`), a checkpoint (`CPn`), the catch-up (`H0`) or the cloud plan. Every code reference in
backticks must point at something that exists, so a renamed module or test breaks the build
rather than the trail:

- a path with a slash (`docs/policies/`, `e2e/auth/interviews.spec.ts`) exists, from the repo
  root or below some directory of it;
- a file name (`test_conductor.py`, `orchestrator.py`) exists somewhere in the repo;
- a dotted module (`hirevion_core.engine`, `engine.timing.TimeController`) resolves to a module
  or package under a Python source root, and any name after it appears in that code.

Anything else in backticks (routes, events, settings, table names) isn't code and isn't checked.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

HEADING = "## Appendix A"
DELIVERY = re.compile(r"SP-\d|§\d|\bCP\d|\bH0\b|Cloud plan|Whole plan", re.IGNORECASE)
ROW = re.compile(r"^\|\s*(?P<section>\d+)\s*\|(?P<requirement>.*)\|(?P<where>[^|]*)\|\s*$")
CODE = re.compile(r"`([^`]+)`")
FILE = re.compile(r"^[\w.-]+\.(py|ts|tsx|mjs|md|json|yaml|yml|toml|sql|rs)$")
MODULE = re.compile(r"^[a-z_][a-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".next", "target", "dist", ".cache"}
)
SOURCE_ROOTS = (
    "backend/core/src",
    "backend/api/src",
    "backend/interview_agent/src",
    "tools/devcli/src",
    "tools/interview-simulator/src",
    "tools/voice_bench/src",
)


@dataclass(frozen=True, slots=True)
class Row:
    section: int
    requirement: str
    where: str
    line: int


@dataclass(frozen=True, slots=True)
class Problem:
    section: int
    line: int
    message: str

    def __str__(self) -> str:
        return f"§{self.section} (line {self.line}): {self.message}"


def appendix_rows(text: str) -> list[Row]:
    """The checklist's rows, from its heading to the next heading."""
    rows: list[Row] = []
    inside = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            inside = line.startswith(HEADING)
            continue
        match = ROW.match(line) if inside else None
        if match:
            rows.append(
                Row(
                    int(match["section"]),
                    match["requirement"].strip(),
                    match["where"].strip(),
                    number,
                )
            )
    return rows


def _walk(root: Path) -> Iterator[Path]:
    for path in root.iterdir():
        if path.name in SKIP_DIRS:
            continue
        yield path
        if path.is_dir() and not path.is_symlink():
            yield from _walk(path)


@cache
def _index(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Every file name and every relative path (files and directories) in the repo."""
    names: set[str] = set()
    paths: set[str] = set()
    for path in _walk(root):
        relative = path.relative_to(root).as_posix()
        paths.add(relative + ("/" if path.is_dir() else ""))
        names.add(path.name)
    return frozenset(names), frozenset(paths)


def _path_exists(root: Path, reference: str) -> bool:
    _, paths = _index(root)
    wanted = reference.lstrip("./")
    return any(path == wanted or path.endswith("/" + wanted) for path in paths)


@cache
def _modules(root: Path) -> dict[str, list[Path]]:
    """Dotted module names (and every dotted suffix of them) to their files or packages."""
    found: dict[str, list[Path]] = {}
    for source in SOURCE_ROOTS:
        base = root / source
        if not base.is_dir():
            continue
        for path in _walk(base):
            if path.is_dir() and (path / "__init__.py").exists():
                parts = path.relative_to(base).parts
            elif path.suffix == ".py" and path.name != "__init__.py":
                parts = (*path.relative_to(base).parent.parts, path.stem)
            else:
                continue
            for start in range(len(parts)):
                found.setdefault(".".join(parts[start:]), []).append(path)
    return found


def _names_in(path: Path, name: str) -> bool:
    files = path.rglob("*.py") if path.is_dir() else [path]
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    return any(pattern.search(file.read_text(encoding="utf-8")) for file in files)


def _module_problem(root: Path, reference: str) -> str | None:
    """None when `reference` resolves (or isn't a module reference at all)."""
    modules = _modules(root)
    parts = reference.split(".")
    if parts[0] not in modules:
        return None  # not a module of ours: a table, an event, a setting
    for split in range(len(parts), 0, -1):
        candidates = modules.get(".".join(parts[:split]))
        if not candidates:
            continue
        rest = parts[split:]
        if not rest or any(all(_names_in(c, name) for name in rest) for c in candidates):
            return None
        return f"`{reference}`: {'.'.join(rest)} isn't in {'.'.join(parts[:split])}"
    return f"`{reference}` isn't a module"


def check(root: Path, plan: Path | None = None) -> list[Problem]:
    text = (plan or root / "MASTER_IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
    rows = appendix_rows(text)
    problems: list[Problem] = []
    if not rows:
        return [Problem(0, 0, "no Appendix A table found")]
    names, _ = _index(root)
    for row in rows:
        if not DELIVERY.search(row.where):
            problems.append(Problem(row.section, row.line, "names no sub-project or plan section"))
        for reference in CODE.findall(row.where):
            token = reference.strip()
            if " " in token or token.startswith("/") or "{" in token or ":" in token:
                continue  # a route, a stream name, a phrase
            if "/" in token:
                if not _path_exists(root, token):
                    problems.append(Problem(row.section, row.line, f"`{token}` doesn't exist"))
            elif FILE.match(token):
                if token not in names:
                    problems.append(Problem(row.section, row.line, f"`{token}` doesn't exist"))
            elif MODULE.match(token):
                problem = _module_problem(root, token)
                if problem:
                    problems.append(Problem(row.section, row.line, problem))
    return problems
