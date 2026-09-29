"""Write or check the committed OpenAPI document (`uv run hv openapi [--check]`).

`packages/api-client/openapi.json` is the contract the TypeScript client is generated from; CI
fails when it differs from what the API serves.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI

from hirevion_api.app import create_app
from hirevion_api.settings import ApiSettings


def openapi_json(app: FastAPI) -> str:
    """The document as stable text: sorted keys, two-space indent, trailing newline."""
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hirevion_api.openapi")
    parser.add_argument("path", type=Path, help="Where the document lives.")
    parser.add_argument("--check", action="store_true", help="Only compare; exit 1 if stale.")
    args = parser.parse_args(argv)

    document = openapi_json(create_app(ApiSettings()))
    path: Path = args.path
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != document:
            print(f"{path} is out of date: run `uv run hv openapi`.", file=sys.stderr)
            return 1
        return 0
    path.write_text(document, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
