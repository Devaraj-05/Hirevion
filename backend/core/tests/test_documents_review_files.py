"""D1 code review of the resume pipeline (SP-04b), continued: ZIP archives, file names and the
images sent to OCR."""

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from PIL import Image

from hirevion_core.documents import archive, ocr
from hirevion_core.documents.files import DocumentRejected, display_name


def zipped(entries: dict[str, bytes], *, store: bool = False) -> bytes:
    out = BytesIO()
    with ZipFile(out, "w", ZIP_STORED if store else ZIP_DEFLATED) as bundle:
        for name, data in entries.items():
            bundle.writestr(name, data)
    return out.getvalue()


def test_one_bad_entry_is_skipped_and_the_rest_of_the_archive_is_read() -> None:
    good = b"Asha Rao, Python developer, Pune"
    data = bytearray(zipped({"good.txt": good, "broken.txt": bytes(range(256)) * 4}))
    # Damage the second entry's deflate stream (but not its header or the directory).
    start = bytes(data).index(b"broken.txt") + len("broken.txt")
    for offset in range(start, start + 6):
        data[offset] ^= 0xFF
    contents = archive.entries(bytes(data))
    assert [entry.name for entry in contents.entries] == ["good.txt"]
    assert [item["name"] for item in contents.skipped] == ["broken.txt"]


def test_an_entry_compressed_like_a_bomb_is_skipped_not_the_whole_archive() -> None:
    contents = archive.entries(
        zipped({"flat.txt": b"\x00" * 5_000_000, "asha.txt": b"Asha Rao, Python developer"})
    )
    assert [entry.name for entry in contents.entries] == ["asha.txt"]
    assert contents.skipped == [{"name": "flat.txt", "reason": "compressed-like-a-bomb"}]


def test_an_archive_with_a_huge_directory_is_refused_before_it_is_opened() -> None:
    many = zipped({f"r{index}.txt": b"x" for index in range(archive.MAX_RECORDS + 1)}, store=True)
    with pytest.raises(DocumentRejected) as refusal:
        archive.entries(many)
    assert refusal.value.code == "archive-too-large"


def test_file_names_are_shown_without_directories_slashes_or_control_characters() -> None:
    assert display_name("..\\..\\evil\\Asha Rao - Résumé (1).pdf") == "Asha Rao - Résumé (1).pdf"
    assert display_name("a/b/c\x00\x07d.pdf") == "cd.pdf"
    assert display_name("///") is None
    contents = archive.entries(zipped({"x/..\\..\\y.txt": b"Asha Rao, Python developer"}))
    assert [entry.name for entry in contents.entries] == ["y.txt"]


def decoded(image: Image.Image) -> Image.Image:
    return Image.open(BytesIO(ocr._png(image)))


def test_a_transparent_image_is_white_paper_not_black() -> None:
    transparent = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    assert decoded(transparent).convert("L").getpixel((0, 0)) == 255


def test_a_photo_taken_sideways_is_turned_upright() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees to display
    out = BytesIO()
    Image.new("RGB", (40, 20), "white").save(out, "JPEG", exif=exif)
    assert decoded(Image.open(BytesIO(out.getvalue()))).size == (20, 40)


def test_a_16_bit_scan_keeps_its_tones_and_a_big_photo_is_scaled_down() -> None:
    assert decoded(Image.new("I;16", (10, 10), 65_000)).getpixel((0, 0)) > 200
    assert max(decoded(Image.new("RGB", (6000, 3000), "white")).size) == ocr.MAX_SIDE


def test_a_tiff_with_too_many_frames_is_refused_before_any_is_read() -> None:
    frames = [Image.new("L", (8, 8), 255) for _ in range(ocr.MAX_FRAMES + 1)]
    out = BytesIO()
    frames[0].save(out, "TIFF", save_all=True, append_images=frames[1:])
    with pytest.raises(DocumentRejected) as refusal:
        ocr._image_pages(out.getvalue())
    assert refusal.value.code == "too-many-pages"
