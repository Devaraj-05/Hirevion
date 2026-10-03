"""Text from images: image resumes (PNG, JPEG and every TIFF frame) and the pages of a PDF that
have no text layer, rendered at 200 dpi. Each page is one call to the OCR service.

An image's identity numbers can only be masked once it's read, so the page image itself goes to
the OCR service unmasked (ADR-0015); the text is masked before it's stored or parsed, and the
call's record keeps no text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from uuid import UUID

import pypdfium2 as pdfium
from PIL import Image, ImageSequence, UnidentifiedImageError

from hirevion_core.ai import AiServices
from hirevion_core.ai.types import AiContext
from hirevion_core.documents.files import DocumentRejected

PURPOSE = "resume.ocr"
MAX_PIXELS = 25_000_000
RENDER_SCALE = 200 / 72
LOW_CONFIDENCE = 0.6


@dataclass(frozen=True, slots=True)
class OcrText:
    page_texts: dict[int, str]
    """Page number (from 1) to its text."""
    confidence: float
    """The mean over the pages read."""


def _png(image: Image.Image) -> bytes:
    if image.width * image.height > MAX_PIXELS:
        raise DocumentRejected("image-too-large")
    out = BytesIO()
    image.convert("L" if image.mode in ("1", "L", "LA", "I;16") else "RGB").save(out, "PNG")
    return out.getvalue()


def _image_pages(data: bytes) -> list[bytes]:
    try:
        with Image.open(BytesIO(data)) as image:
            # The header alone tells the size: refuse before decoding a bomb.
            if image.width * image.height > MAX_PIXELS:
                raise DocumentRejected("image-too-large")
            return [_png(frame.copy()) for frame in ImageSequence.Iterator(image)]
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise DocumentRejected("unreadable") from error


def _pdf_pages(data: bytes, pages: Sequence[int]) -> list[bytes]:
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise DocumentRejected("unreadable") from error
    try:
        rendered = []
        for number in pages:
            page = document[number - 1]
            width, height = page.get_size()
            if width * height * RENDER_SCALE**2 > MAX_PIXELS:
                raise DocumentRejected("image-too-large")
            rendered.append(_png(page.render(scale=RENDER_SCALE).to_pil()))
        return rendered
    finally:
        document.close()


async def read(
    ai: AiServices,
    organization_id: UUID,
    data: bytes,
    kind: str,
    pages: Sequence[int] | None = None,
    *,
    document_id: UUID,
) -> OcrText:
    """The text of an image file's frames, or of the given (1-based) pages of a PDF."""
    if kind == "pdf":
        numbers = list(pages or [])
        images = _pdf_pages(data, numbers)
    elif kind in ("png", "jpeg", "tiff"):
        images = _image_pages(data)
        numbers = list(range(1, len(images) + 1))
    else:
        raise DocumentRejected("unsupported-type")

    texts: dict[int, str] = {}
    confidences: list[float] = []
    for number, image in zip(numbers, images, strict=True):
        context = AiContext(
            organization_id=organization_id,
            purpose=PURPOSE,
            input_refs={"document": str(document_id), "page": str(number)},
        )
        page = await ai.ocr.read_page(context, image, "image/png")
        texts[number] = page.text
        confidences.append(page.confidence)
    confidence = sum(confidences) / len(confidences) if confidences else 1.0
    return OcrText(texts, confidence)
