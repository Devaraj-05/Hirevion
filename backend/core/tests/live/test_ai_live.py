"""Opt-in checks against the real vendors (`uv run pytest --live backend/core/tests/live`).

They use the keys in `.env`, cost a few cents, and never run in CI. The `dev` profile is Gemini
(and Deepgram); OpenAI is checked when `OPENAI_API_KEY` and `HV_OPENAI_TEST_MODEL` are set.
"""

import math
import os
import struct
import zlib
from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from pydantic import BaseModel

from hirevion_core.ai.openai_compat import OpenAICompatible
from hirevion_core.ai.prices import PriceBook
from hirevion_core.ai.recorder import Recorder
from hirevion_core.ai.settings import AiSettings, load_ai_settings
from hirevion_core.ai.types import AiContext
from hirevion_core.db.session import Database

pytestmark = pytest.mark.live

MakeOrganization = Callable[[str], Awaitable[UUID]]


def backend_for(provider: str, app_db: Database) -> OpenAICompatible:
    settings = load_ai_settings()
    if provider == "gemini":
        if not settings.gemini_api_key.get_secret_value():
            pytest.skip("GEMINI_API_KEY is not set")
        return OpenAICompatible(settings, Recorder(app_db, PriceBook.load(), settings), "gemini")
    model = os.environ.get("HV_OPENAI_TEST_MODEL", "")
    if not settings.openai_api_key.get_secret_value() or not model:
        pytest.skip("set OPENAI_API_KEY and HV_OPENAI_TEST_MODEL to check OpenAI")
    production: AiSettings = settings.model_copy(
        update={
            "profile": "production",
            "llm_model_fast": model,
            "llm_model_strong": model,
            "vision_model": model,
            "embedding_model": "text-embedding-3-large",
        }
    )
    return OpenAICompatible(production, Recorder(app_db, PriceBook.load(), production), "openai")


@pytest.fixture(params=["gemini", "openai"])
def backend(request: pytest.FixtureRequest, app_db: Database) -> OpenAICompatible:
    return backend_for(request.param, app_db)


class Capital(BaseModel):
    city: str


@pytest.mark.parametrize("tier", ["fast", "strong"])
async def test_a_structured_answer(
    backend: OpenAICompatible, make_organization: MakeOrganization, tier: str
) -> None:
    org = await make_organization("LiveLlm")
    result = await backend.complete(
        AiContext(org, "live.check"),
        [{"role": "user", "content": "What is the capital city of India?"}],
        Capital,
        tier=tier,  # type: ignore[arg-type]
    )
    assert "delhi" in result.value.city.lower()
    assert result.input_tokens > 0


async def test_embeddings_have_the_configured_size(
    backend: OpenAICompatible, make_organization: MakeOrganization
) -> None:
    org = await make_organization("LiveEmbed")
    result = await backend.embed(
        AiContext(org, "live.check"), ["Senior Python engineer", "Python developer", "Chef"]
    )
    close, far = result.vectors[0], result.vectors[2]
    assert [len(vector) for vector in result.vectors] == [1536] * 3
    assert math.isclose(sum(value * value for value in close), 1.0, rel_tol=1e-6)

    def similarity(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert similarity(close, result.vectors[1]) > similarity(close, far)


# A 5x7 bitmap font for the one word the OCR check needs.
GLYPHS = {
    "H": ["X...X", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"],
    "I": ["XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "XXXXX"],
    "R": ["XXXX.", "X...X", "X...X", "XXXX.", "X.X..", "X..X.", "X...X"],
    "E": ["XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"],
    "V": ["X...X", "X...X", "X...X", "X...X", "X...X", ".X.X.", "..X.."],
    "O": [".XXX.", "X...X", "X...X", "X...X", "X...X", "X...X", ".XXX."],
    "N": ["X...X", "XX..X", "X.X.X", "X..XX", "X...X", "X...X", "X...X"],
}


def word_png(word: str, scale: int = 10, margin: int = 20) -> bytes:
    """A black-on-white grayscale PNG of `word`, drawn without an imaging library."""
    columns: list[str] = []
    for index, letter in enumerate(word):
        glyph = GLYPHS[letter]
        columns += ["".join(row[col] for row in glyph) for col in range(5)]
        if index < len(word) - 1:
            columns.append("." * 7)
    width, height = len(columns) * scale + 2 * margin, 7 * scale + 2 * margin
    rows = []
    for y in range(height):
        row = bytearray(b"\xff" * width)
        glyph_y = (y - margin) // scale
        if 0 <= glyph_y < 7 and y >= margin:
            for x_col, column in enumerate(columns):
                if column[glyph_y] == "X":
                    start = margin + x_col * scale
                    row[start : start + scale] = b"\x00" * scale
        rows.append(b"\x00" + bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


async def test_ocr_reads_a_rendered_word(
    backend: OpenAICompatible, make_organization: MakeOrganization
) -> None:
    org = await make_organization("LiveOcr")
    page = await backend.read_page(AiContext(org, "live.check"), word_png("HIREVION"), "image/png")
    assert "HIREVION" in page.text.upper().replace(" ", "")
    assert 0 <= page.confidence <= 1
