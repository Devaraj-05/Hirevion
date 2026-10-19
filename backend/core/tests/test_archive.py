"""ZIP uploads of resumes (SP-04b Task 4): entries, skips and refusals."""

import zipfile
from collections.abc import Callable
from io import BytesIO

import pytest

from hirevion_core.documents import archive
from hirevion_core.documents.files import DocumentRejected


def zipped(files: dict[str, bytes]) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return out.getvalue()


def test_resumes_come_out_and_the_rest_is_skipped_with_reasons(
    make_pdf: Callable[..., bytes], make_docx: Callable[..., bytes]
) -> None:
    contents = archive.entries(
        zipped(
            {
                "resumes/asha.pdf": make_pdf("Asha Rao"),
                "resumes/ravi.docx": make_docx("Ravi Kumar"),
                "resumes/meera.txt": b"Meera Iyer, Data analyst",
                "__MACOSX/resumes/._asha.pdf": b"junk",
                ".DS_Store": b"junk",
                "inner.zip": zipped({"x.txt": b"nested"}),
                "song.mp3": b"ID3\x04\x00\x00\x00\x00\x00\x00binary\x00\x00",
            }
        )
    )
    assert [(entry.name, entry.kind) for entry in contents.entries] == [
        ("asha.pdf", "pdf"),
        ("ravi.docx", "docx"),
        ("meera.txt", "txt"),
    ]
    assert {skip["name"]: skip["reason"] for skip in contents.skipped} == {
        "inner.zip": "nested-archive",
        "song.mp3": "unsupported-type",
    }


def test_a_zip_bomb_is_never_expanded() -> None:
    # Skipped with its reason (and so reported to the recruiter), never read.
    contents = archive.entries(zipped({"bomb.txt": b"0" * (5 * 1024 * 1024)}))
    assert contents.entries == []
    assert contents.skipped == [{"name": "bomb.txt", "reason": "compressed-like-a-bomb"}]


def test_too_many_entries_are_refused() -> None:
    files = {f"cv-{index}.txt": f"Candidate {index}".encode() for index in range(201)}
    with pytest.raises(DocumentRejected) as refusal:
        archive.entries(zipped(files))
    assert refusal.value.code == "archive-too-large"


def test_a_broken_zip_is_unreadable() -> None:
    with pytest.raises(DocumentRejected) as refusal:
        archive.entries(b"PK\x03\x04 not really a zip")
    assert refusal.value.code == "unreadable"


def test_zips_are_recognised_by_their_bytes(make_docx: Callable[..., bytes]) -> None:
    from hirevion_core.documents.files import sniff

    assert sniff(zipped({"a.txt": b"hello"})) == "zip"
    assert sniff(make_docx("Asha")) == "docx"
