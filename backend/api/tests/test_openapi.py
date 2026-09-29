"""The committed OpenAPI document is exactly what the API serves (master plan §13)."""

import json
from pathlib import Path

import pytest

from hirevion_api.app import create_app
from hirevion_api.openapi import main, openapi_json
from hirevion_api.settings import ApiSettings

COMMITTED = Path(__file__).resolve().parents[3] / "packages" / "api-client" / "openapi.json"


def test_the_document_is_stable_text() -> None:
    first = openapi_json(create_app(ApiSettings()))
    assert first == openapi_json(create_app(ApiSettings()))
    assert first.endswith("}\n")
    assert json.loads(first)["openapi"].startswith("3.1")


def test_the_committed_document_is_current() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == openapi_json(create_app(ApiSettings())), (
        "Run `uv run hv openapi` and `pnpm --filter @hirevion/api-codegen generate`."
    )


def test_write_then_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "openapi.json"
    assert main([str(target), "--check"]) == 1
    assert str(target) in capsys.readouterr().err
    assert main([str(target)]) == 0
    assert main([str(target), "--check"]) == 0
    target.write_text("{}\n", encoding="utf-8")
    assert main([str(target), "--check"]) == 1
