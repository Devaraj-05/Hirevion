"""Report PDFs (SP-17; ADR-0023): rendered by Chromium from the report's HTML with no script and no
network, so a PDF holds the document's text and nothing a candidate's words could add."""

from __future__ import annotations

from io import BytesIO

import pdfplumber
import pytest

from hirevion_core.reports import blocks as b
from hirevion_core.reports.exports import render_pdf
from hirevion_core.reports.pdf import PdfUnavailable, PlaywrightPdfRenderer


def document() -> b.Document:
    return b.document(
        "interview",
        "Interview report",
        "IV-0007 · Asha Rao · Backend Engineer",
        [
            b.section(
                "executive_summary",
                "Executive summary",
                [
                    b.facts([("Candidate", "Asha Rao"), ("Overall score", "7.4 of 10")]),
                    b.table(
                        "Skill scores",
                        ["Skill", "Score"],
                        [["PostgreSQL", "8.1"], ["Python", "6.5"]],
                    ),
                    b.quotes([("I would run EXPLAIN ANALYZE first.", "Turn 4 at 1:02")]),
                    b.text("<script>alert('x')</script> is only text in a report."),
                ],
            ),
            b.section("coding_evaluation", "Coding evaluation", [b.notice("SP-16")], pending=True),
        ],
    )


@pytest.fixture
async def pdf() -> bytes:
    try:
        return await render_pdf(PlaywrightPdfRenderer(), document())
    except PdfUnavailable:
        pytest.skip("Chromium isn't installed: run `uv run playwright install chromium`")


async def test_the_pdf_is_a_pdf_with_the_reports_text(pdf: bytes) -> None:
    assert pdf.startswith(b"%PDF-")
    with pdfplumber.open(BytesIO(pdf)) as opened:
        text = "\n".join(page.extract_text() or "" for page in opened.pages)
    assert "Interview report" in text and "Asha Rao" in text
    assert "PostgreSQL" in text and "7.4 of 10" in text
    assert "EXPLAIN ANALYZE" in text
    assert "CONFIDENTIAL" in text
    assert "<script>alert('x')</script> is only text" in text
    assert "Page 1 of" in text


async def test_the_page_cannot_reach_the_network_or_run_script() -> None:
    renderer = PlaywrightPdfRenderer()
    page = (
        '<html><body><img src="http://127.0.0.1:9/beacon.png"><p id="p">static</p>'
        "<script>document.getElementById('p').textContent = 'changed by script'</script>"
        "</body></html>"
    )
    try:
        data = await renderer.render(page, footer="test")
    except PdfUnavailable:
        pytest.skip("Chromium isn't installed")
    with pdfplumber.open(BytesIO(data)) as opened:
        text = opened.pages[0].extract_text() or ""
    assert "static" in text and "changed by script" not in text
