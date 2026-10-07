"""
Фото, которые загружают пользователи: товары, логотипы магазинов, обложки
каналов.

Раньше файл сохранялся как есть с лимитом 5 МБ. Лимит подняли до 20 МБ —
снимок с современного телефона весит 8–15 МБ, — и хранить такие файлы как
есть уже нельзя: каталог грузил бы фотографии по десятку мегабайт на каждую
карточку. Поэтому:

  * кадр уменьшается до MAX_SIDE по большей стороне — для витрины этого с
    запасом, а файл весит сотни килобайт;
  * файл перекодируется без EXIF: в снимке с телефона там координаты места
    съёмки и модель устройства, а фото товара видят все;
  * формат сохраняется: JPEG остаётся JPEG, PNG с прозрачностью — PNG.

Тип определяется по содержимому через Pillow, а не по расширению и
content-type — и то и другое подделывается тривиально.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

MAX_SIDE = 2000
JPEG_QUALITY = 85

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


class ImageError(Exception):
    pass


def prepare(content: bytes, max_bytes: int) -> tuple[bytes, str]:
    """Проверяет и пережимает картинку. Возвращает байты и расширение файла."""
    if len(content) > max_bytes:
        raise ImageError(f"Файл больше {max_bytes // 1024 // 1024} МБ")

    try:
        Image.open(io.BytesIO(content)).verify()   # ловит битые и поддельные файлы
        # verify() оставляет объект непригодным — открываем заново
        image = Image.open(io.BytesIO(content))
        fmt = (image.format or "").upper()
        image.load()
    except Exception:
        raise ImageError("Файл не является изображением")

    if fmt not in ALLOWED_FORMATS:
        raise ImageError(
            f"Формат {fmt or 'неизвестный'} не поддерживается. "
            f"Допустимы: {', '.join(sorted(ALLOWED_FORMATS))}"
        )

    # Поворот по EXIF — до того, как EXIF исчезнет: иначе снимок с телефона
    # ляжет на бок
    image = ImageOps.exif_transpose(image)
    image.thumbnail((MAX_SIDE, MAX_SIDE))

    # Прозрачность палитры переносится конвертацией, поэтому режим меняем до
    # того, как выбросить метаданные
    if fmt == "JPEG":
        image = image.convert("RGB")
    elif image.mode not in ("RGB", "RGBA", "L", "LA"):
        image = image.convert("RGBA")

    # Метаданные исходника (EXIF, XMP) выбрасываем целиком, а exif=b"" ещё и
    # явно: часть форматов берёт его из info, если не передать
    image.info.clear()
    out = io.BytesIO()
    if fmt == "JPEG":
        image.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True, exif=b"")
    elif fmt == "WEBP":
        image.save(out, "WEBP", quality=JPEG_QUALITY, exif=b"")
    else:
        image.save(out, "PNG", optimize=True, exif=b"")

    return out.getvalue(), EXTENSIONS[fmt]
