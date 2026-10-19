"""The text inside a PDF, DOCX or text file, page by page. Text a reader can't see (white on the
page, under 3 pt, off the page, drawn invisible or painted over; hidden runs in Word) is left out
and kept apart, since that is how resumes smuggle instructions to AI screeners (master plan
§3.2(3)). White text on a dark banner or a shaded cell is visible, and stays. Images and pages
with no text layer go to OCR (`documents.ocr`)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import pdfplumber
from charset_normalizer import from_bytes
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.page import PDFPageAggregatorWithMarkedContent
from pdfplumber.utils.exceptions import PdfminerException

from hirevion_core.documents.files import DocumentRejected, inflation_check

MAX_PAGES = 50
# Smaller than this, text is unreadable on screen or paper.
MIN_FONT_POINTS = 3.0
# A page with fewer visible characters than this is a scan, or an image of text.
OCR_THRESHOLD = 20
_WHITE = 0.9
_DARK = 0.5
# Painted shapes beyond these are not tracked: a page of vector art is not a hiding place.
_MAX_SHAPES = 500
_INVISIBLE = 3  # PDF text rendering mode 3: neither filled nor stroked
_METADATA_KEYS = ("Title", "Subject", "Keywords", "Author", "Creator")
_DARK_HIGHLIGHTS = frozenset(
    {
        "black",
        "blue",
        "darkBlue",
        "darkCyan",
        "darkGray",
        "darkGreen",
        "darkMagenta",
        "darkRed",
        "darkYellow",
    }
)


@dataclass(frozen=True, slots=True)
class ExtractedText:
    text: str
    pages: int
    page_texts: tuple[str, ...] = ()
    hidden: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


# PDF


def _luminance(color: Any) -> float | None:
    """0 (black) to 1 (white) for a gray, RGB or CMYK colour; None when it isn't one."""
    if not isinstance(color, (tuple, list)) or not color:
        return None
    try:
        values = [float(value) for value in color]
    except (TypeError, ValueError):
        return None
    if len(values) == 4:  # CMYK
        cyan, magenta, yellow, black = values
        return (
            (1 - min(1.0, cyan + black)) * 0.3
            + (1 - min(1.0, magenta + black)) * 0.59
            + (1 - min(1.0, yellow + black)) * 0.11
        )
    if len(values) == 3:
        return 0.3 * values[0] + 0.59 * values[1] + 0.11 * values[2]
    if len(values) == 1:
        return values[0]
    return None


def _is_white(color: Any) -> bool:
    if isinstance(color, (tuple, list)) and len(color) == 4:  # CMYK: white has no ink
        try:
            return all(float(value) <= 1 - _WHITE for value in color)
        except (TypeError, ValueError):
            return False
    if isinstance(color, (tuple, list)) and len(color) == 3:
        try:
            return all(float(value) >= _WHITE for value in color)
        except (TypeError, ValueError):
            return False
    luminance = _luminance(color)
    return luminance is not None and luminance >= _WHITE


class _Layout(PDFPageAggregatorWithMarkedContent):
    """pdfplumber's layout device, which also notes how each character was drawn: its text
    rendering mode, so invisible text can be told apart from text on the page."""

    _mode = 0

    def render_string(self, textstate: Any, seq: Any, ncs: Any, graphicstate: Any) -> None:
        self._mode = int(getattr(textstate, "render", 0) or 0)
        super().render_string(textstate, seq, ncs, graphicstate)

    def render_char(self, *args: Any, **kwargs: Any) -> float:
        advance = super().render_char(*args, **kwargs)
        if self.cur_item._objs:
            setattr(self.cur_item._objs[-1], "hv_mode", self._mode)  # noqa: B010
        return advance


def _key(x0: float, top: float, text: str) -> tuple[float, float, str]:
    return round(float(x0), 1), round(float(top), 1), text


def _drawn(page: Any) -> tuple[set[Any], set[Any]]:
    """The characters of `page` that are never shown or sit on a dark ground. The first set is
    the characters drawn invisible or painted over by a later white shape; the second is the
    ones laid on a darker shape, where white text is legible. Both are keyed by position."""
    device = _Layout(page.pdf.rsrcmgr, pageno=page.page_number, laparams=page.pdf.laparams)
    try:
        PDFPageInterpreter(page.pdf.rsrcmgr, device).process_page(page.page_obj)
    except Exception as error:  # a malformed page: pdfminer raises whatever it tripped on
        raise PdfminerException(error) from error
    layout = device.get_result()
    page._layout = layout  # pdfplumber reads the characters from this, so they match ours
    height = float(page.height)
    drawn = list(_walk(layout))
    if sum(hasattr(obj, "hv_mode") for obj in drawn) != len(page.chars):
        return set(), set()  # not the same characters pdfplumber sees: trust none of it
    invisible: set[Any] = set()
    on_dark: set[Any] = set()
    placed: list[tuple[Any, Any]] = []  # (LTChar, key), in drawing order
    dark: list[tuple[float, float, float, float]] = []
    shapes = 0
    for obj in drawn:
        if hasattr(obj, "hv_mode"):
            char_key = _key(obj.x0, height - obj.y1, obj.get_text())
            if obj.hv_mode == _INVISIBLE:
                invisible.add(char_key)
            center = ((obj.x0 + obj.x1) / 2, (obj.y0 + obj.y1) / 2)
            if any(x0 <= center[0] <= x1 and y0 <= center[1] <= y1 for x0, y0, x1, y1 in dark):
                on_dark.add(char_key)
            placed.append((obj, char_key))
        elif getattr(obj, "fill", False) and shapes < _MAX_SHAPES:
            shapes += 1
            luminance = _luminance(getattr(obj, "non_stroking_color", None))
            if luminance is None:
                continue
            x0, y0, x1, y1 = obj.bbox
            if luminance >= _WHITE:  # a white shape hides what was drawn before it
                for char, char_key in placed:
                    cx, cy = (char.x0 + char.x1) / 2, (char.y0 + char.y1) / 2
                    if x0 <= cx <= x1 and y0 <= cy <= y1:
                        invisible.add(char_key)
            elif luminance < _DARK:
                dark.append((x0, y0, x1, y1))
    return invisible, on_dark


def _walk(container: Any) -> Iterator[Any]:
    """The layout's objects in drawing order, going into figures (form XObjects)."""
    for obj in container._objs:
        if hasattr(obj, "_objs") and not hasattr(obj, "hv_mode"):
            yield from _walk(obj)
        else:
            yield obj


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
    inflation_check(data, "pdf")
    try:
        with pdfplumber.open(BytesIO(data)) as document:
            if len(document.pages) > MAX_PAGES:
                raise DocumentRejected("too-many-pages")
            page_texts: list[str] = []
            hidden: list[str] = []
            for page in document.pages:
                width, height = page.width, page.height
                invisible, on_dark = _drawn(page)

                def seen(
                    obj: dict[str, Any],
                    width: float = width,
                    height: float = height,
                    invisible: set[Any] = invisible,
                    on_dark: set[Any] = on_dark,
                ) -> bool:
                    if obj.get("object_type") != "char":
                        return True
                    on_page = (
                        obj["x1"] > 0
                        and obj["x0"] < width
                        and obj["bottom"] > 0
                        and obj["top"] < height
                    )
                    key = _key(obj["x0"], obj["top"], obj["text"])
                    return (
                        on_page
                        and float(obj.get("size") or 0) >= MIN_FONT_POINTS
                        and key not in invisible
                        and (not _is_white(obj.get("non_stroking_color")) or key in on_dark)
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
    except DocumentRejected:
        raise
    except (PDFSyntaxError, PdfminerException, ValueError, KeyError, TypeError) as error:
        raise DocumentRejected("unreadable") from error
    except Exception as error:  # a damaged file can make pdfminer fail in any way
        raise DocumentRejected("unreadable") from error
    return ExtractedText(
        "\f".join(page_texts), len(page_texts), tuple(page_texts), "\n".join(hidden), metadata
    )


# Word

_PARAGRAPH_RUNS = (
    "./w:r | ./w:hyperlink//w:r | ./w:ins//w:r | ./w:smartTag//w:r | ./w:fldSimple//w:r"
    " | ./w:sdt/w:sdtContent//w:r"
)
_TEXT_BOXES = (
    ".//*[local-name()='txbxContent'][not(ancestor::*[local-name()='Fallback'])]"
    "[not(ancestor::*[local-name()='txbxContent'])]"
)


def _fill_dark(element: Any) -> bool:
    """Whether a shading element (`w:shd`) fills with a dark colour."""
    if element is None:
        return False
    fill = element.get(qn("w:fill"))
    if not fill or len(fill) != 6:
        return False
    try:
        red, green, blue = (int(fill[index : index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError:
        return False
    return 0.3 * red + 0.59 * green + 0.11 * blue < _DARK


def _on_dark(run: Run, paragraph: Paragraph) -> bool:
    """Whether the run sits on a dark ground: its own shading or highlight, its paragraph's, or
    its table cell's."""
    properties = run._r.rPr
    if properties is not None:
        highlight = properties.find(qn("w:highlight"))
        if highlight is not None and highlight.get(qn("w:val")) in _DARK_HIGHLIGHTS:
            return True
        if _fill_dark(properties.find(qn("w:shd"))):
            return True
    if paragraph._p.pPr is not None and _fill_dark(paragraph._p.pPr.find(qn("w:shd"))):
        return True
    for cell in paragraph._p.iterancestors(qn("w:tc")):
        shading = cell.find(qn("w:tcPr") + "/" + qn("w:shd"))
        if _fill_dark(shading):
            return True
    return False


def _styled(run: Run, paragraph: Paragraph) -> list[Any]:
    """The fonts that apply to a run, from its own settings to its styles."""
    fonts = [run.font]
    for style in (run.style, paragraph.style):
        if style is not None:
            fonts.append(style.font)
    return fonts


def _run_hidden(run: Run, paragraph: Paragraph) -> bool:
    fonts = _styled(run, paragraph)
    if any(font.hidden for font in fonts):
        return True
    size = next((font.size for font in fonts if font.size is not None), None)
    if size is not None and size.pt < MIN_FONT_POINTS:
        return True
    color = next((font.color for font in fonts if font.color.type is not None), None)
    rgb = color.rgb if color is not None else None
    white = rgb is not None and all(part >= 0xE6 for part in rgb)
    return white and not _on_dark(run, paragraph)


def _blocks(element: Any, parent: Any) -> Iterator[Paragraph | Table]:
    """The paragraphs and tables inside `element`, in document order (content controls open)."""
    for child in element.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)
        elif child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _blocks(content, parent)


def _paragraph_lines(paragraph: Paragraph, hidden: list[str]) -> list[str]:
    shown: list[str] = []
    secret: list[str] = []
    for element in paragraph._p.xpath(_PARAGRAPH_RUNS):
        run = Run(element, paragraph)
        (secret if _run_hidden(run, paragraph) else shown).append(run.text)
    if secret:
        hidden.append("".join(secret))
    lines = ["".join(shown)]
    for box in paragraph._p.xpath(_TEXT_BOXES):
        for inner in _blocks(box, paragraph):
            lines += _block_lines(inner, hidden)
    return lines


def _block_lines(block: Paragraph | Table, hidden: list[str]) -> list[str]:
    if isinstance(block, Paragraph):
        return _paragraph_lines(block, hidden)
    lines: list[str] = []
    for row in block._tbl.tr_lst:
        cells = []
        for cell_element in row.tc_lst:
            cell = _Cell(cell_element, block)
            parts = [
                line
                for inner in _blocks(cell._tc, cell)
                for line in _block_lines(inner, hidden)
                if line
            ]
            cells.append(" ".join(parts))
        lines.append("\t".join(cells))
    return lines


def _docx(data: bytes) -> ExtractedText:
    inflation_check(data, "docx")
    hidden: list[str] = []
    try:
        document = DocxDocument(BytesIO(data))
        body: list[str] = []
        for block in _blocks(document.element.body, document):
            body += _block_lines(block, hidden)
        top: list[str] = []
        bottom: list[str] = []
        seen: set[str] = set()
        for section in document.sections:
            for part, into in (
                (section.header, top),
                (section.first_page_header, top),
                (section.even_page_header, top),
                (section.footer, bottom),
                (section.first_page_footer, bottom),
                (section.even_page_footer, bottom),
            ):
                if part.is_linked_to_previous:
                    continue
                lines = [
                    line
                    for block in _blocks(part._element, part)
                    for line in _block_lines(block, hidden)
                ]
                text = "\n".join(lines).strip()
                if text and text not in seen:
                    seen.add(text)
                    into.append(text)
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
    except DocumentRejected:
        raise
    except Exception as error:  # a damaged file can make python-docx or lxml fail in any way
        raise DocumentRejected("unreadable") from error
    text = "\n".join([*top, *body, *bottom])
    return ExtractedText(text, 1, (text,), "\n".join(part for part in hidden if part), metadata)


# Text


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
