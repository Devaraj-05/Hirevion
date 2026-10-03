"""OCR of image resumes and scanned PDF pages (SP-04b Task 4), through the mock AI."""

from collections.abc import Awaitable, Callable
from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image, ImageDraw

from hirevion_core.ai import AiServices, build_ai
from hirevion_core.ai.mock import MockOCR
from hirevion_core.ai.settings import AiSettings
from hirevion_core.db.session import Database
from hirevion_core.documents import ocr
from hirevion_core.documents.files import DocumentRejected
from hirevion_core.ids import uuid7

pytestmark = pytest.mark.db

MakeOrganization = Callable[[str], Awaitable[UUID]]


def image(kind: str, frames: int = 1, size: tuple[int, int] = (400, 200)) -> bytes:
    pages = []
    for number in range(frames):
        page = Image.new("L", size, 255)
        ImageDraw.Draw(page).text((10, 10), f"Asha Rao page {number + 1}", fill=0)
        pages.append(page)
    out = BytesIO()
    pages[0].save(out, format=kind, save_all=frames > 1, append_images=pages[1:])
    return out.getvalue()


@pytest.fixture
def ai(app_db: Database) -> AiServices:
    services = build_ai(AiSettings(profile="mock"), app_db)
    assert isinstance(services.ocr, MockOCR)
    services.ocr.scripted["resume.ocr"] = "Asha Rao, Python developer"
    return services


async def test_an_image_resume_is_read(ai: AiServices, make_organization: MakeOrganization) -> None:
    org = await make_organization("Acme")
    read = await ocr.read(ai, org, image("PNG"), "png", document_id=uuid7())
    assert read.page_texts == {1: "Asha Rao, Python developer"}
    assert read.confidence == pytest.approx(0.99)


async def test_every_frame_of_a_tiff_is_a_page(
    ai: AiServices, make_organization: MakeOrganization
) -> None:
    org = await make_organization("Acme")
    read = await ocr.read(ai, org, image("TIFF", frames=2), "tiff", document_id=uuid7())
    assert sorted(read.page_texts) == [1, 2]
    assert isinstance(ai.ocr, MockOCR) and ai.ocr.calls == 2


async def test_only_the_scanned_pages_of_a_pdf_are_read(
    ai: AiServices, make_organization: MakeOrganization, make_pdf_pages: Callable[..., bytes]
) -> None:
    org = await make_organization("Acme")
    document = make_pdf_pages("BT /F1 12 Tf 72 720 Td (A page with text) Tj ET", "")
    read = await ocr.read(ai, org, document, "pdf", pages=[2], document_id=uuid7())
    assert read.page_texts == {2: "Asha Rao, Python developer"}


async def test_huge_images_are_refused(ai: AiServices, make_organization: MakeOrganization) -> None:
    org = await make_organization("Acme")
    with pytest.raises(DocumentRejected) as refusal:
        await ocr.read(ai, org, image("PNG", size=(6000, 5000)), "png", document_id=uuid7())
    assert refusal.value.code == "image-too-large"
    assert isinstance(ai.ocr, MockOCR) and ai.ocr.calls == 0
