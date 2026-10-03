"""ZIP uploads of resumes (PRD §13 bulk upload). Entries are read in memory, each bounded, and
never written to disk; the archive as a whole is refused when it is too big or compressed like a
bomb, and entries we won't take are skipped with a reason."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from io import BytesIO

from hirevion_core.documents.files import MAX_BYTES, DocumentRejected, FileKind, sniff

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_ENTRIES = 200
MAX_UNCOMPRESSED = 200 * 1024 * 1024
MAX_RATIO = 100
RESUME_KINDS: frozenset[str] = frozenset({"pdf", "docx", "txt", "png", "jpeg", "tiff"})


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


def entries(data: bytes) -> ArchiveContents:
    try:
        bundle = zipfile.ZipFile(BytesIO(data))
        infos = [info for info in bundle.infolist() if not info.is_dir()]
    except (zipfile.BadZipFile, ValueError) as error:
        raise DocumentRejected("unreadable") from error
    files = [info for info in infos if not _junk(info.filename)]
    if len(files) > MAX_ENTRIES or sum(info.file_size for info in files) > MAX_UNCOMPRESSED:
        raise DocumentRejected("archive-too-large")
    for info in files:
        if info.file_size > MAX_RATIO * max(info.compress_size, 1):
            raise DocumentRejected("archive-bomb")

    contents = ArchiveContents()
    for info in files:
        name = info.filename.rsplit("/", 1)[-1]
        if info.flag_bits & 0x1:
            contents.skipped.append({"name": name, "reason": "encrypted"})
            continue
        if info.file_size > MAX_BYTES:
            contents.skipped.append({"name": name, "reason": "too-large"})
            continue
        try:
            with bundle.open(info) as stream:
                content = stream.read(MAX_BYTES + 1)  # the declared size may lie
        except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
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
