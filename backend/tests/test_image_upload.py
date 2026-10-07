"""
Фото товаров, логотипов и обложек: до 20 МБ на входе, на диске — уменьшенная
копия без метаданных. Иначе каталог грузил бы снимки с телефона по десятку
мегабайт, а EXIF раздавал бы координаты места съёмки.
"""

import io

import pytest
from PIL import Image

from services import image_upload

LIMIT = 20 * 1024 * 1024


def _photo(fmt: str = "JPEG", size=(4000, 3000), mode="RGB") -> bytes:
    image = Image.new(mode, size, (30, 120, 200) if mode == "RGB" else (30, 120, 200, 128))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[0x0110] = "PhoneModel X"
    buffer = io.BytesIO()
    image.save(buffer, fmt, exif=exif)
    return buffer.getvalue()


def test_big_photo_is_shrunk_and_metadata_dropped():
    data, extension = image_upload.prepare(_photo(), LIMIT)

    saved = Image.open(io.BytesIO(data))
    assert extension == ".jpg"
    assert max(saved.size) == image_upload.MAX_SIDE
    assert not saved.getexif()


def test_transparent_png_stays_png():
    data, extension = image_upload.prepare(_photo("PNG", (800, 600), "RGBA"), LIMIT)

    saved = Image.open(io.BytesIO(data))
    assert extension == ".png"
    assert saved.mode == "RGBA"
    assert saved.size == (800, 600)      # маленькое не растягивается


def test_too_big_file_is_refused():
    with pytest.raises(image_upload.ImageError, match="больше 1 МБ"):
        image_upload.prepare(b"x" * (1024 * 1024 + 1), 1024 * 1024)


def test_not_an_image_is_refused():
    with pytest.raises(image_upload.ImageError):
        image_upload.prepare(b"<svg onload=alert(1)>", LIMIT)
