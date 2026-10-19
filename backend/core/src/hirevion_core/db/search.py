"""Helpers for searching text columns."""

from __future__ import annotations


def like_escape(value: str) -> str:
    """`value` as the literal text of a LIKE pattern (used with `escape="\\\\"`): `%` and `_`
    match themselves instead of anything."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
