"""The price book: what one call costs in USD, from list prices with named sources."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

PRICES_FILE = Path(__file__).with_name("prices.yaml")
_MILLION = Decimal(1_000_000)
_PRICE_FIELDS = (
    "input_per_million_tokens",
    "output_per_million_tokens",
    "per_minute",
    "per_thousand_characters",
)


class PriceBook:
    def __init__(self, entries: Mapping[str, Mapping[str, Any]]) -> None:
        self.entries = {model: dict(entry) for model, entry in entries.items()}

    @classmethod
    def load(cls, path: Path = PRICES_FILE) -> PriceBook:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(document.get("models", {}))

    @property
    def models(self) -> list[str]:
        return list(self.entries)

    def _entry(self, model: str) -> Mapping[str, Any] | None:
        if model in self.entries:
            return self.entries[model]
        for pattern, entry in self.entries.items():
            if "*" in pattern and fnmatchcase(model, pattern):
                return entry
        return None

    def _prices(self, model: str, on: date) -> Mapping[str, Any] | None:
        entry = self._entry(model)
        if entry is None or "periods" not in entry:
            return entry
        for period in entry["periods"]:
            until = period.get("until")
            if until is None or on <= until:
                return dict(period)
        return None

    def cost(
        self,
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        seconds: Decimal | float = 0,
        characters: int = 0,
        on: date | None = None,
    ) -> Decimal | None:
        """USD for this usage, or `None` when the model has no known price."""
        prices = self._prices(model, on or datetime.now(UTC).date())
        if prices is None:
            return None
        rate = {name: Decimal(str(prices.get(name, "0"))) for name in _PRICE_FIELDS}
        return (
            rate["input_per_million_tokens"] * input_tokens / _MILLION
            + rate["output_per_million_tokens"] * output_tokens / _MILLION
            + rate["per_minute"] * Decimal(str(seconds)) / 60
            + rate["per_thousand_characters"] * characters / 1000
        )
