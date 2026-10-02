"""Fixtures for the core tests: tiny, real documents, a one-page PDF (built by hand, with a
correct cross-reference table) and a DOCX (built with python-docx), and the EICAR string."""

from __future__ import annotations

from collections.abc import Callable
from io import BytesIO

import pytest
from docx import Document as DocxDocument

# The EICAR anti-virus test string: harmless, and every scanner reports it.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def pdf(*lines: str) -> bytes:
    """A one-page PDF showing `lines` in Helvetica."""
    text_ops = "\n".join(
        f"BT /F1 12 Tf 72 {720 - 18 * index} Td ({line}) Tj ET" for index, line in enumerate(lines)
    ).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(text_ops)).encode() + b" >>\nstream\n" + text_ops + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def docx(*paragraphs: str) -> bytes:
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Skill"
    table.rows[0].cells[1].text = "Kubernetes"
    out = BytesIO()
    document.save(out)
    return out.getvalue()


@pytest.fixture
def make_pdf() -> Callable[..., bytes]:
    return pdf


@pytest.fixture
def make_docx() -> Callable[..., bytes]:
    return docx


@pytest.fixture
def eicar() -> bytes:
    return EICAR
