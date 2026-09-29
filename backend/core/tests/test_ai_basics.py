"""AI provider layer pieces that need no database: prices, context rules, the mocks."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import BaseModel

from hirevion_core.ai.mock import fake_instance, fake_vector
from hirevion_core.ai.prices import PriceBook
from hirevion_core.ai.types import AiContext

ORG = UUID("01920000-0000-7000-8000-000000000001")

BOOK = PriceBook(
    {
        "chat-model": {"input_per_million_tokens": "0.10", "output_per_million_tokens": "0.40"},
        "listen-model": {"per_minute": "0.0060"},
        "speak-model": {"per_thousand_characters": "0.030"},
    }
)


def test_token_prices_are_per_million() -> None:
    cost = BOOK.cost("chat-model", input_tokens=2_000_000, output_tokens=500_000)
    assert cost == Decimal("0.40")


def test_audio_is_priced_per_minute_and_speech_per_thousand_characters() -> None:
    assert BOOK.cost("listen-model", seconds=Decimal(90)) == Decimal("0.0090")
    assert BOOK.cost("speak-model", characters=2_500) == Decimal("0.075")


def test_prices_can_change_on_a_date() -> None:
    book = PriceBook(
        {
            "dated": {
                "periods": [
                    {"until": date(2026, 12, 31), "input_per_million_tokens": "0.75"},
                    {"input_per_million_tokens": "1.50"},
                ]
            }
        }
    )
    million = 1_000_000
    assert book.cost("dated", input_tokens=million, on=date(2026, 12, 31)) == Decimal("0.75")
    assert book.cost("dated", input_tokens=million, on=date(2027, 1, 1)) == Decimal("1.50")


def test_a_pattern_prices_a_family_of_models() -> None:
    book = PriceBook({"voice-*": {"per_thousand_characters": "0.030"}})
    assert book.cost("voice-thalia-en", characters=1_000) == Decimal("0.030")
    assert book.cost("other-thalia-en", characters=1_000) is None


def test_an_unknown_model_has_no_price() -> None:
    assert BOOK.cost("unpriced-model", input_tokens=10) is None


def test_every_shipped_price_names_its_source_and_date() -> None:
    book = PriceBook.load()
    assert book.models, "prices.yaml lists no models"
    for model, entry in book.entries.items():
        assert str(entry.get("source", "")).startswith("https://"), model
        assert isinstance(entry.get("retrieved"), date), model


@pytest.mark.parametrize("purpose", ["", "Screening", "has space", "x" * 65])
def test_purposes_are_short_dotted_names(purpose: str) -> None:
    with pytest.raises(ValueError, match="purpose"):
        AiContext(ORG, purpose)


def test_fake_vectors_are_deterministic_and_unit_length() -> None:
    first = fake_vector("Senior Python engineer", 1536)
    assert first == fake_vector("Senior Python engineer", 1536)
    assert first != fake_vector("Data scientist", 1536)
    assert len(first) == 1536
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9


class Nested(BaseModel):
    label: str
    weight: float


class Verdict(BaseModel):
    score: int
    passed: bool
    summary: str
    tags: list[str]
    nested: Nested
    note: str | None = None


def test_fake_instances_satisfy_their_schema() -> None:
    verdict = fake_instance(Verdict)
    assert isinstance(verdict, Verdict)
    assert verdict == fake_instance(Verdict)
