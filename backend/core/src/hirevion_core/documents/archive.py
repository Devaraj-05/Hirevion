"""ZIP uploads of resumes (PRD §13 bulk upload). Entries are read in memory, each bounded, and
never written to disk; the archive as a whole is refused when it has too many records or is too
big, and entries we won't take (encrypted, too big, compressed like a bomb, damaged, not a
resume) are skipped with a reason, so one bad file doesn't sink the rest."""

from __future__ import annotations

import lzma
import zipfile
import zlib
from dataclasses import dataclass, field
from io import BytesIO

from hirevion_core.documents.files import (
    MAX_BYTES,
    RESUME_KINDS,
    DocumentRejected,
    FileKind,
    display_name,
    sniff,
)

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ENTRIES = 200
MAX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_RATIO = 100
# The records a ZIP's directory may hold before it is opened: the entries, folders and the
# macOS junk that travels with them. Reading the directory costs memory per record.
MAX_RECORDS = 4 * MAX_ENTRIES


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    name: str
    data: bytes
    kind: FileKind


@dataclass(frozen=True, slots=True)
class ArchiveContents:
    entries: list[ArchiveEntry] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def _junk(path: str) -> bool:
    """Folders, macOS resource forks and dotfiles: not things anyone uploaded on purpose."""
    return path.startswith("__MACOSX/") or path.rsplit("/", 1)[-1].startswith(".")


def _declared_records(data: bytes) -> int | None:
    """How many records the archive's end-of-directory says it has, without opening it."""
    tail = data[-(65_535 + 22) :]
    index = tail.rfind(b"PK\x05\x06")
    if index < 0 or len(tail) - index < 22:
        return None
    return int.from_bytes(tail[index + 10 : index + 12], "little")


def entries(data: bytes) -> ArchiveContents:
    declared = _declared_records(data)
    if declared is not None and declared > MAX_RECORDS:
        raise DocumentRejected("archive-too-large")
    try:
        bundle = zipfile.ZipFile(BytesIO(data))
        infos = [info for info in bundle.infolist() if not info.is_dir()]
    except (zipfile.BadZipFile, ValueError, NotImplementedError) as error:
        raise DocumentRejected("unreadable") from error
    files = [info for info in infos if not _junk(info.filename)]
    if len(files) > MAX_ENTRIES or sum(info.file_size for info in files) > MAX_UNCOMPRESSED:
        raise DocumentRejected("archive-too-large")

    contents = ArchiveContents()
    for info in files:
        name = display_name(info.filename) or "resume"
        if info.flag_bits & 0x1:
            contents.skipped.append({"name": name, "reason": "encrypted"})
            continue
        if info.file_size > MAX_BYTES:
            contents.skipped.append({"name": name, "reason": "too-large"})
            continue
        if info.file_size > MAX_RATIO * max(info.compress_size, 1):
            contents.skipped.append({"name": name, "reason": "compressed-like-a-bomb"})
            continue
        try:
            with bundle.open(info) as stream:
                content = stream.read(MAX_BYTES + 1)  # the declared size may lie
        except (
            zipfile.BadZipFile,
            RuntimeError,
            OSError,
            EOFError,
            zlib.error,
            lzma.LZMAError,
            NotImplementedError,
            ValueError,
        ):
            contents.skipped.append({"name": name, "reason": "unreadable"})
            continue
        if len(content) > MAX_BYTES:
            contents.skipped.append({"name": name, "reason": "too-large"})
            continue
        kind = sniff(content) if content else None
        if kind == "zip":
            contents.skipped.append({"name": name, "reason": "nested-archive"})
        elif kind is None or kind not in RESUME_KINDS:
            contents.skipped.append({"name": name, "reason": "unsupported-type"})
        else:
            contents.entries.append(ArchiveEntry(name, content, kind))
    return contents
