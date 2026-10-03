"""What a file really is, from its bytes (never its name), and whether to accept it."""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Literal

from charset_normalizer import from_bytes

FileKind = Literal["pdf", "docx", "txt", "png", "jpeg", "tiff", "zip"]

MAX_BYTES = 10 * 1024 * 1024


class DocumentRejected(Exception):
    """A file we won't process: `code` says why (`empty`, `too-large`, `unsupported-type`,
    `unreadable`)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except (zipfile.BadZipFile, ValueError):
        return False


def _is_text(data: bytes) -> bool:
    if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        best = from_bytes(data[:65536]).best()
        return best is not None and best.chaos < 0.1
    return True


def sniff(data: bytes) -> FileKind | None:
    """The file's type from its first bytes, or None when it's none we handle."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "docx" if _is_docx(data) else "zip"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if _is_text(data):
        return "txt"
    return None


def check(data: bytes, allowed: set[str], max_bytes: int = MAX_BYTES) -> FileKind:
    """The file's type, if it's one of `allowed` and not too big; otherwise `DocumentRejected`."""
    if not data:
        raise DocumentRejected("empty")
    if len(data) > max_bytes:
        raise DocumentRejected("too-large")
    kind = sniff(data)
    if kind is None or kind not in allowed:
        raise DocumentRejected("unsupported-type")
    return kind
