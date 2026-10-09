"""The traceability check (H0): Appendix A's rows name where they're delivered, and every code
reference in them exists."""

from pathlib import Path

from hirevion_devcli.trace import appendix_rows, check

PLAN = """# Plan

## 14. Sub-projects

| 1 | Not the appendix | nowhere |

## Appendix A — PRD traceability checklist

| § | Requirement | Delivered by |
|---|---|---|
| 1 | Engine | SP-09 (`hirevion_core.engine`, `engine.timing.TimeController`, `test_engine.py`) |
| 2 | Policies | H0 (`docs/policies/`) |
| 3 | Routes and events aren't code | SP-09 (`/ws/interviews/{id}`, `AI_SPEAKING`, `hv:rt:x`) |
| 4 | Nowhere | someday |
| 5 | Stale | SP-09 (`docs/gone/`, `missing_test.py`, `engine.timing.Gone`, `engine.nope`) |
| 6 | A checkpoint | CP3 |

## Appendix B
"""


def repo(tmp_path: Path) -> Path:
    package = tmp_path / "backend/core/src/hirevion_core/engine"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    (package / "timing.py").write_text("class TimeController:\n    pass\n")
    (tmp_path / "docs/policies").mkdir(parents=True)
    (tmp_path / "backend/core/tests").mkdir(parents=True)
    (tmp_path / "backend/core/tests/test_engine.py").write_text("")
    (tmp_path / "MASTER_IMPLEMENTATION_PLAN.md").write_text(PLAN, encoding="utf-8")
    return tmp_path


def test_only_the_appendix_rows_are_read() -> None:
    rows = appendix_rows(PLAN)
    assert [row.section for row in rows] == [1, 2, 3, 4, 5, 6]
    assert rows[1].where == "H0 (`docs/policies/`)"


def test_rows_must_name_a_delivery_and_point_at_code_that_exists(tmp_path: Path) -> None:
    problems = [str(p) for p in check(repo(tmp_path))]
    assert problems == [
        "§4 (line 14): names no sub-project or plan section",
        "§5 (line 15): `docs/gone/` doesn't exist",
        "§5 (line 15): `missing_test.py` doesn't exist",
        "§5 (line 15): `engine.timing.Gone`: Gone isn't in engine.timing",
        "§5 (line 15): `engine.nope`: nope isn't in engine",
    ]


def test_the_master_plans_checklist_holds() -> None:
    root = Path(__file__).resolve().parents[3]
    assert [str(p) for p in check(root)] == []
