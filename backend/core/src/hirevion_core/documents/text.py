"""The text inside a PDF, DOCX or text file. Images and scanned pages need OCR (SP-04b)."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pdfplumber
from charset_normalizer import from_bytes
from docx import Document as DocxDocument
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from hirevion_core.documents.files import DocumentRejected

MAX_PAGES = 50


@dataclass(frozen=True, slots=True)
class ExtractedText:
    text: str
    pages: int


def _pdf(data: bytes) -> ExtractedText:
    try:
        with pdfplumber.open(BytesIO(data)) as document:
            if len(document.pages) > MAX_PAGES:
                raise DocumentRejected("too-many-pages")
            pages = [page.extract_text() or "" for page in document.pages]
    except (PDFSyntaxError, PdfminerException, ValueError, KeyError, TypeError) as error:
        raise DocumentRejected("unreadable") from error
    return ExtractedText("\f".join(pages), len(pages))


def _docx(data: bytes) -> ExtractedText:
    try:
        document = DocxDocument(BytesIO(data))
    except (ValueError, KeyError) as error:
        raise DocumentRejected("unreadable") from error
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.append("\t".join(cell.text for cell in row.cells))
    return ExtractedText("\n".join(lines), 1)


def _txt(data: bytes) -> ExtractedText:
    try:
        return ExtractedText(data.decode("utf-8-sig"), 1)
    except UnicodeDecodeError:
        best = from_bytes(data).best()
        if best is None:
            raise DocumentRejected("unreadable") from None
        return ExtractedText(str(best), 1)


def extract(data: bytes, kind: str) -> ExtractedText:
    """The file's text (pages separated by form feeds), or `DocumentRejected("unreadable")`."""
    readers = {"pdf": _pdf, "docx": _docx, "txt": _txt}
    if kind not in readers:
        raise DocumentRejected("unsupported-type")
    return readers[kind](data)
