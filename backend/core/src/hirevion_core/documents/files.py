"""What a file really is, from its bytes (never its name), and whether to accept it."""

from __future__ import annotations

import re
import zipfile
import zlib
from io import BytesIO
from typing import Literal

from charset_normalizer import from_bytes

FileKind = Literal["pdf", "docx", "txt", "png", "jpeg", "tiff", "zip"]

MAX_BYTES = 10 * 1024 * 1024
# What a resume may be, on its own or as an entry of a ZIP.
RESUME_KINDS: frozenset[str] = frozenset({"pdf", "docx", "txt", "png", "jpeg", "tiff"})
# What a Word file may inflate to, and what one PDF stream, and all of a PDF's, may. A small
# upload that expands past these is a decompression bomb, not a resume.
MAX_INFLATED = 64 * 1024 * 1024
MAX_PDF_STREAM = 64 * 1024 * 1024
MAX_PDF_INFLATED = 256 * 1024 * 1024
_PDF_STREAM = re.compile(rb"(?<!end)stream\r?\n(.*?)endstream", re.DOTALL)


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


def display_name(name: str) -> str | None:
    """The last part of an uploaded file's path, for showing. The stored file is named by its
    id, so this is never used as a path: it only drops directories, either slash, and control
    characters."""
    last = name.replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(char for char in last if char.isprintable()).strip()[:255] or None


def inflation_check(data: bytes, kind: str) -> None:
    """Refuses a Word file or PDF that expands to a bomb (`archive-bomb`). The sizes a ZIP states
    are the sizes it is read at, and a PDF's deflate streams are inflated with a ceiling."""
    if kind == "docx":
        try:
            with zipfile.ZipFile(BytesIO(data)) as bundle:
                total = sum(info.file_size for info in bundle.infolist())
        except (zipfile.BadZipFile, ValueError) as error:
            raise DocumentRejected("unreadable") from error
        if total > MAX_INFLATED:
            raise DocumentRejected("archive-bomb")
    elif kind == "pdf":
        total = 0
        for match in _PDF_STREAM.finditer(data):
            inflater = zlib.decompressobj()
            try:
                inflated = inflater.decompress(match.group(1), MAX_PDF_STREAM)
            except zlib.error:
                continue  # not deflated (an image, a font file, encrypted): nothing to expand
            if inflater.unconsumed_tail:
                raise DocumentRejected("archive-bomb")
            total += len(inflated)
            if total > MAX_PDF_INFLATED:
                raise DocumentRejected("archive-bomb")


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
    inflation_check(data, kind)
    return kind
