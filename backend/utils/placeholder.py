"""
Картинка-заглушка для товаров без фото.

На неё ссылались все товары подписок (`/uploads/products/placeholder.png`), а
самого файла в томе не было — nginx отдавал 404, и карточка в витрине
выходила пустой. Класть картинку в репозиторий незачем: uploads живёт в
именованном томе, который при первом запуске пуст, и файл из образа туда всё
равно не попадёт.

Поэтому рисуем её при старте, если её нет. Ничего не перезаписываем: если
администратор положил туда свою картинку, она останется.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw

from config import settings

logger = logging.getLogger(__name__)

SIZE = 600
# Нейтральный серый, одинаково сносный и в светлой, и в тёмной теме: акцент
# площадки сюда тянуть нельзя — картинка лежит в томе и переживёт смену цвета.
BACKGROUND = (38, 38, 38)
FOREGROUND = (115, 115, 115)


def ensure_placeholder() -> Path | None:
    """Создаёт заглушку, если её ещё нет. Возвращает путь или None при ошибке."""
    path = Path(settings.UPLOAD_DIR) / "products" / "placeholder.png"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return path

        image = Image.new("RGB", (SIZE, SIZE), BACKGROUND)
        draw = ImageDraw.Draw(image)

        # Силуэт картинки: рамка, «горизонт» и кружок-солнце. Рисуем
        # примитивами, а не шрифтом — шрифта в образе может не оказаться.
        margin = SIZE // 5
        draw.rounded_rectangle(
            [margin, margin, SIZE - margin, SIZE - margin],
            radius=24, outline=FOREGROUND, width=6,
        )
        draw.ellipse(
            [margin + 40, margin + 40, margin + 100, margin + 100],
            outline=FOREGROUND, width=6,
        )
        draw.line(
            [
                (margin + 20, SIZE - margin - 40),
                (SIZE // 2 - 30, SIZE // 2 + 20),
                (SIZE // 2 + 60, SIZE - margin - 40),
            ],
            fill=FOREGROUND, width=6, joint="curve",
        )

        image.save(path, "PNG", optimize=True)
        logger.info("[UPLOADS] Создана заглушка %s", path)
        return path
    except Exception as e:
        # Картинка — украшение: из-за неё приложение стартовать не откажется
        logger.warning("[UPLOADS] Заглушка не создана: %s", e)
        return None
