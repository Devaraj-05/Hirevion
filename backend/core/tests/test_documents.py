"""Documents: the file's real type, its size, the virus scan, its text and its sections
(SP-04a Task 4)."""

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest

from hirevion_core.documents.files import DocumentRejected, check, sniff
from hirevion_core.documents.scan import ClamdScanner, FakeScanner, ScanUnavailable
from hirevion_core.documents.sections import detect, normalise
from hirevion_core.documents.text import extract

# Types


def test_the_type_comes_from_the_bytes_not_the_name(
    make_pdf: Callable[..., bytes], make_docx: Callable[..., bytes]
) -> None:
    assert sniff(make_pdf("Hello")) == "pdf"
    assert sniff(make_docx("Hello")) == "docx"
    assert sniff(b"Senior engineer, Bengaluru") == "txt"
    assert sniff(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16) == "png"
    assert sniff(b"\xff\xd8\xff\xe0" + b"\x00" * 16) == "jpeg"
    assert sniff(b"II*\x00" + b"\x00" * 16) == "tiff"
    assert sniff(b"MZ\x90\x00\x03\x00\x00\x00" + bytes(range(256))) is None


def test_a_file_is_refused_when_wrong(make_pdf: Callable[..., bytes]) -> None:
    allowed = {"pdf", "docx", "txt"}
    assert check(make_pdf("Hello"), allowed) == "pdf"
    for data, limit, code in (
        (b"", 10, "empty"),
        (b"MZ" + bytes(range(256)), 1024, "unsupported-type"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, 1024, "unsupported-type"),
        (b"a" * 11, 10, "too-large"),
    ):
        with pytest.raises(DocumentRejected) as refusal:
            check(data, allowed, max_bytes=limit)
        assert refusal.value.code == code


# Text


def test_text_comes_out_of_each_format(
    make_pdf: Callable[..., bytes], make_docx: Callable[..., bytes]
) -> None:
    extracted = extract(make_pdf("Senior Python Engineer", "Kubernetes and AWS"), "pdf")
    assert "Senior Python Engineer" in extracted.text and "Kubernetes" in extracted.text
    assert extracted.pages == 1
    word = extract(make_docx("Requirements", "5 years of Go"), "docx")
    assert "5 years of Go" in word.text and "Kubernetes" in word.text
    assert extract("Plain JD text".encode("utf-16"), "txt").text == "Plain JD text"


def test_a_broken_file_is_unreadable() -> None:
    with pytest.raises(DocumentRejected) as refusal:
        extract(b"%PDF-1.4\nnot really a pdf", "pdf")
    assert refusal.value.code == "unreadable"


# Normalisation and sections


def test_normalising_removes_hidden_characters_and_counts_them() -> None:
    text, hidden = normalise("Py\u200bthon\u00a0developer\r\n\r\n\r\n\uff27\uff4f  \u202eskills")
    assert text == "Python developer\n\nGo skills"
    assert hidden == 2


def test_sections_are_found_by_their_headings() -> None:
    text = (
        "Senior Engineer\n\nAbout us\nWe hire.\n\nResponsibilities:\n- Build APIs\n\n"
        "REQUIREMENTS\n- 5 years of Python\n\nBenefits\n- Health cover\n"
    )
    names = [section.name for section in detect(text)]
    assert names == ["about", "responsibilities", "requirements", "benefits"]
    requirements = next(s for s in detect(text) if s.name == "requirements")
    assert "5 years of Python" in text[requirements.start : requirements.end]


# Scanning


async def test_the_fake_scanner_catches_eicar(eicar: bytes) -> None:
    scanner = FakeScanner()
    assert (await scanner.scan(b"a clean resume")).clean
    infected = await scanner.scan(b"prefix " + eicar)
    assert (infected.clean, infected.signature) == (False, "Eicar-Test-Signature")


@pytest.fixture
async def clamd(eicar: bytes) -> AsyncIterator[tuple[str, int, list[bytes]]]:
    """A stand-in clamd: answers INSTREAM like the real one, `FOUND` when the stream holds
    EICAR."""
    received: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        body = b""
        while size := int.from_bytes(await reader.readexactly(4), "big"):
            body += await reader.readexactly(size)
        received.append(body)
        writer.write(b"stream: Eicar-Signature FOUND\0" if eicar in body else b"stream: OK\0")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield "127.0.0.1", port, received


async def test_clamd_is_asked_over_instream(
    clamd: tuple[str, int, list[bytes]], eicar: bytes
) -> None:
    host, port, received = clamd
    scanner = ClamdScanner(host, port, chunk_size=8)
    assert (await scanner.scan(b"a clean job description")).clean
    infected = await scanner.scan(eicar)
    assert (infected.clean, infected.signature) == (False, "Eicar-Signature")
    assert received[0] == b"a clean job description"


async def test_an_unreachable_scanner_is_unavailable_not_clean() -> None:
    with pytest.raises(ScanUnavailable):
        await ClamdScanner("127.0.0.1", 1, timeout=0.5).scan(b"anything")
