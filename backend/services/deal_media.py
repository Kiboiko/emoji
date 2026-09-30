"""
Фото в переписке по сделке.

Здесь не витрина, а переписка двух людей: покупатель присылает скриншот
настроек аккаунта, продавец — фото ключа или логина. Поэтому два правила,
которых нет у фото товаров:

  * файл перекодируется, а не сохраняется как есть. Снимок с телефона несёт
    в EXIF координаты места съёмки и модель устройства — отдавать это
    второй стороне незачем. Заодно кадр уменьшается до разумного размера;

  * файл лежит вне публичной папки uploads (ту целиком раздаёт nginx) и
    отдаётся только по подписанной ссылке с ограниченным сроком. Картинку
    браузер грузит тегом img без заголовка авторизации, поэтому доступ
    доказывает подпись в самой ссылке, а выдаёт её только эндпоинт,
    проверивший участника сделки.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import re
import time
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from config import settings

# Большая сторона кадра после уменьшения: скриншот телефона читается целиком,
# а файл весит сотни килобайт, а не мегабайты
MAX_SIDE = 1600
JPEG_QUALITY = 85

# Ссылка живёт несколько часов и округлена до часа: в пределах часа адрес не
# меняется, и браузер берёт картинку из кеша, а не качает заново при каждом
# открытии чата
LINK_TTL_SECONDS = 6 * 3600

_NAME = re.compile(r"^[0-9a-f]{32}_[0-9a-f]{32}\.jpg$")


class MediaError(Exception):
    pass


def media_dir() -> Path:
    path = Path(settings.DEAL_MEDIA_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_photo(content: bytes, deal_id: uuid.UUID) -> str:
    """
    Проверяет, перекодирует и сохраняет фото. Возвращает имя файла.

    Тип определяется по содержимому через Pillow, а не по расширению и
    content-type — и то и другое подделывается тривиально.
    """
    if len(content) > settings.DEAL_MEDIA_MAX_SIZE:
        raise MediaError(
            f"Фото больше {settings.DEAL_MEDIA_MAX_SIZE // 1024 // 1024} МБ"
        )

    try:
        Image.open(io.BytesIO(content)).verify()
        # verify() оставляет объект непригодным — открываем заново
        image = Image.open(io.BytesIO(content))
        image.load()
    except Exception:
        raise MediaError("Файл не является изображением")

    # Поворот по EXIF применяем до того, как EXIF исчезнет вместе с
    # перекодированием, иначе снимок с телефона ляжет на бок
    image = ImageOps.exif_transpose(image)

    if image.mode in ("RGBA", "LA", "P"):
        # Прозрачность — на белый фон: в JPEG её нет, а чёрный фон вместо
        # прозрачного у скриншота выглядит поломкой
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    else:
        image = image.convert("RGB")

    image.thumbnail((MAX_SIDE, MAX_SIDE))

    name = f"{deal_id.hex}_{uuid.uuid4().hex}.jpg"
    # Без exif=: Pillow не переносит метаданные, если их не передать явно
    image.save(media_dir() / name, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return name


def _signature(name: str, expires: int) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"deal-media:{name}:{expires}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


def signed_url(name: str) -> str:
    """Ссылка на фото, которую можно вставить в img."""
    expires = (int(time.time()) // 3600 + 1) * 3600 + LINK_TTL_SECONDS
    return f"/api/p2p/deal-media/{name}?e={expires}&s={_signature(name, expires)}"


def resolve(name: str, expires: int, signature: str) -> Path:
    """
    Путь к файлу по подписанной ссылке.

    Имя проверяется по шаблону до обращения к диску: без этого подпись
    пришлось бы считать и для «../../.env».
    """
    if not _NAME.match(name):
        raise MediaError("Нет такого файла")
    if expires < time.time():
        raise MediaError("Ссылка устарела")
    if not hmac.compare_digest(_signature(name, expires), signature):
        raise MediaError("Нет такого файла")

    path = media_dir() / name
    if not path.is_file():
        raise MediaError("Нет такого файла")
    return path
