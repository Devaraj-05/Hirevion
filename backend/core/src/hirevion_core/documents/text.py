"""The text inside a PDF, DOCX or text file, page by page. Text a reader can't see (white, under
3 pt, or off the page; hidden runs in Word) is left out and kept apart, since that is how
resumes smuggle instructions to AI screeners (master plan §3.2(3)). Images and pages with no
text layer go to OCR (`documents.ocr`)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import pdfplumber
from charset_normalizer import from_bytes
from docx import Document as DocxDocument
from docx.shared import RGBColor
from docx.text.run import Run
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from hirevion_core.documents.files import DocumentRejected

MAX_PAGES = 50
# Smaller than this, text is unreadable on screen or paper.
MIN_FONT_POINTS = 3.0
# A page with fewer visible characters than this is a scan, or an image of text.
OCR_THRESHOLD = 20
_WHITE = 0.9
_METADATA_KEYS = ("Title", "Subject", "Keywords", "Author", "Creator")


@dataclass(frozen=True, slots=True)
class ExtractedText:
    text: str
    pages: int
    page_texts: tuple[str, ...] = ()
    hidden: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


def _is_white(color: Any) -> bool:
    if not isinstance(color, (tuple, list)) or not color:
        return False
    try:
        values = [float(value) for value in color]
    except (TypeError, ValueError):
        return False
    if len(values) == 4:  # CMYK: white has no ink
        return all(value <= 1 - _WHITE for value in values)
    return all(value >= _WHITE for value in values)


def _lines(chars: list[dict[str, Any]]) -> str:
    """Characters as text, with a line break wherever the next one sits on another line."""
    out: list[str] = []
    previous: float | None = None
    for char in chars:
        if previous is not None and abs(float(char["top"]) - previous) > 1:
            out.append("\n")
        out.append(char["text"])
        previous = float(char["top"])
    return "".join(out)


def _pdf(data: bytes) -> ExtractedText:
    try:
        with pdfplumber.open(BytesIO(data)) as document:
            if len(document.pages) > MAX_PAGES:
                raise DocumentRejected("too-many-pages")
            page_texts: list[str] = []
            hidden: list[str] = []
            for page in document.pages:
                width, height = page.width, page.height

                def seen(obj: dict[str, Any], width: float = width, height: float = height) -> bool:
                    if obj.get("object_type") != "char":
                        return True
                    on_page = (
                        obj["x1"] > 0
                        and obj["x0"] < width
                        and obj["bottom"] > 0
                        and obj["top"] < height
                    )
                    return (
                        on_page
                        and float(obj.get("size") or 0) >= MIN_FONT_POINTS
                        and not _is_white(obj.get("non_stroking_color"))
                    )

                page_texts.append(page.filter(seen).extract_text() or "")
                unseen = _lines([char for char in page.chars if not seen(char)])
                if unseen:
                    hidden.append(unseen)
            metadata = {
                key: str(document.metadata[key]).strip()
                for key in _METADATA_KEYS
                if isinstance(document.metadata.get(key), (str, bytes))
                and str(document.metadata[key]).strip()
            }
    except (PDFSyntaxError, PdfminerException, ValueError, KeyError, TypeError) as error:
        raise DocumentRejected("unreadable") from error
    return ExtractedText(
        "\f".join(page_texts), len(page_texts), tuple(page_texts), "\n".join(hidden), metadata
    )


def _run_hidden(run: Run) -> bool:
    font = run.font
    if font.hidden:
        return True
    if font.size is not None and font.size.pt < MIN_FONT_POINTS:
        return True
    rgb = font.color.rgb if font.color is not None and font.color.type is not None else None
    return isinstance(rgb, RGBColor) and all(part >= 0xE6 for part in rgb)


def _docx(data: bytes) -> ExtractedText:
    try:
        document = DocxDocument(BytesIO(data))
    except (ValueError, KeyError) as error:
        raise DocumentRejected("unreadable") from error
    hidden: list[str] = []

    def visible_text(paragraphs: Sequence[Any]) -> list[str]:
        lines = []
        for paragraph in paragraphs:
            shown: list[str] = []
            for run in paragraph.runs:
                (hidden if _run_hidden(run) else shown).append(run.text)
            lines.append("".join(shown) if paragraph.runs else paragraph.text)
        return lines

    lines = visible_text(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            lines.append("\t".join(" ".join(visible_text(cell.paragraphs)) for cell in row.cells))
    core = document.core_properties
    metadata = {
        key: value.strip()
        for key, value in (
            ("Title", core.title),
            ("Subject", core.subject),
            ("Keywords", core.keywords),
            ("Author", core.author),
        )
        if value and value.strip()
    }
    text = "\n".join(lines)
    return ExtractedText(text, 1, (text,), "".join(hidden), metadata)


def _txt(data: bytes) -> ExtractedText:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        best = from_bytes(data).best()
        if best is None:
            raise DocumentRejected("unreadable") from None
        text = str(best)
    return ExtractedText(text, 1, (text,))


def extract(data: bytes, kind: str) -> ExtractedText:
    """The file's visible text (pages separated by form feeds) and what was hidden, or
    `DocumentRejected("unreadable")`."""
    readers = {"pdf": _pdf, "docx": _docx, "txt": _txt}
    if kind not in readers:
        raise DocumentRejected("unsupported-type")
    return readers[kind](data)


def needs_ocr(page_texts: Sequence[str]) -> list[int]:
    """The (1-based) pages with almost no text layer: scans, or images of text."""
    return [
        number
        for number, text in enumerate(page_texts, start=1)
        if len("".join(text.split())) < OCR_THRESHOLD
    ]
