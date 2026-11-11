"""
Облегчённые копии загруженных фото.

Продавцы загружают картинки как есть, и image_upload.prepare сохраняет формат:
PNG остаётся PNG. Сгенерированная картинка 2000×2000 в PNG весит 2–4 МБ, и
каталог из десятка таких тормозил на телефоне: файлы тяжело качать, а
распаковывать каждую в плитку шириной в полэкрана — ещё тяжелее.

Оригинал не трогаем: на него ссылаются товары, объявления и снимки сделок, и
переписывать адреса в базе ради веса файла — риск без пользы. Рядом кладём
две WebP-копии, путь которых повторяет адрес оригинала на сайте:

    _web/uploads/listings/<имя>.png.v3.webp    до 1024 px — страница товара;
    _thumb/uploads/listings/<имя>.png.v3.webp  до 384 px — каталог и списки;
    _cart/uploads/listings/<имя>.png.v3.webp   до 160 px — корзина.

nginx (nginx/nginx.conf) по адресу оригинала отдаёт копию, если она есть, и
сам оригинал, если нет, — адреса в базе и в коде прежние, а без копий всё
работает как раньше. Картинка с настоящей прозрачностью сохраняется в WebP:
JPEG залил бы прозрачное чёрным.

Если копия выходит не легче оригинала, вместо неё кладётся
пустая метка .v2.skip. Версия отличает их от ранее созданных JPEG-копий. Копия и
метка считаются годными, пока они не старше оригинала: аватар канала
перезаписывается под тем же именем, и копия от прошлой картинки иначе так бы
и отдавалась.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

VARIANTS = {"_web": 1024, "_thumb": 384, "_cart": 160}
QUALITY = {"_web": 80, "_thumb": 76, "_cart": 76}
SOURCE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
CURRENT_SUFFIX = ".v3.webp"
# Retain legacy suffixes for removal of already uploaded files.
OUTPUT_SUFFIXES = (CURRENT_SUFFIX, ".v2.webp", ".v2.skip", ".jpg", ".webp", ".skip")
SKIP_SUFFIX = ".v3.skip"
# Копия легче оригинала меньше чем на десятую часть не стоит лишнего файла
MIN_SAVING = 0.9


def variant_base(root: Path, variant: str, source: Path) -> Path:
    """Путь копии без расширения: _web/uploads/<путь оригинала>."""
    return root / variant / "uploads" / source.relative_to(root)


def _with_suffix(base: Path, suffix: str) -> Path:
    return base.with_name(base.name + suffix)


def _is_fresh(base: Path, source_mtime: float) -> bool:
    for suffix in (CURRENT_SUFFIX, SKIP_SUFFIX):
        path = _with_suffix(base, suffix)
        if path.exists() and path.stat().st_mtime >= source_mtime:
            return True
    return False


def _drop(base: Path, legacy: bool = True) -> None:
    suffixes = (*OUTPUT_SUFFIXES, SKIP_SUFFIX) if legacy else (CURRENT_SUFFIX, SKIP_SUFFIX)
    for suffix in suffixes:
        _with_suffix(base, suffix).unlink(missing_ok=True)


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        alpha = image.convert("RGBA").getchannel("A")
        return alpha.getextrema()[0] < 255
    return False


def build(root: Path, source: Path, force: bool = False) -> int:
    """
    Готовит недостающие копии одного файла. Возвращает, сколько записано.

    force=True — пересобрать, даже если копии свежие: так делает загрузка,
    когда файл перезаписан под тем же именем в ту же секунду.
    """
    source_mtime = source.stat().st_mtime
    pending = []
    for variant, side in VARIANTS.items():
        base = variant_base(root, variant, source)
        if force or not _is_fresh(base, source_mtime):
            pending.append((base, side, QUALITY[variant]))
    if not pending:
        return 0

    original_size = source.stat().st_size
    written = 0
    with Image.open(source) as opened:
        opened.load()
        image = ImageOps.exif_transpose(opened)
        alpha = _has_alpha(image)
        image = image.convert("RGBA" if alpha else "RGB")

        for base, side, quality in pending:
            copy = image.copy()
            copy.thumbnail((side, side), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            copy.save(out, "WEBP", quality=quality, method=4)
            suffix = CURRENT_SUFFIX

            _drop(base, legacy=False)
            base.parent.mkdir(parents=True, exist_ok=True)
            if out.tell() >= original_size * MIN_SAVING:
                _with_suffix(base, SKIP_SUFFIX).touch()
                continue

            # Через временный файл: nginx не должен отдать половину картинки
            target = _with_suffix(base, suffix)
            temporary = _with_suffix(target, ".tmp")
            temporary.write_bytes(out.getvalue())
            temporary.replace(target)
            written += 1
    return written


def remove(root: Path, url: str) -> bool:
    """
    Удаляет загруженный файл и его облегчённые копии. True — файл был удалён.

    Нужна модерации: фото, которое нужно убрать, не должно оставаться
    доступным по прямой ссылке. Ссылка приходит из базы, но проверяется всё
    равно — путь не должен выйти из каталога загрузок, а заглушку товаров
    удалять нельзя: на неё ссылаются все товары без фото.
    """
    base_url = url.split("?", 1)[0]
    if not base_url.startswith("/uploads/"):
        return False
    resolved_root = root.resolve()
    source = (root / base_url[len("/uploads/"):]).resolve()
    if resolved_root not in source.parents:
        return False
    if source.name == "placeholder.png":
        return False

    for variant in VARIANTS:
        _drop(variant_base(resolved_root, variant, source))

    if not source.is_file():
        return False
    source.unlink()
    return True


def build_quietly(root: Path, source: Path, force: bool = False) -> int:
    """Копии — ускорение, а не часть загрузки: сбой здесь не роняет запрос."""
    try:
        return build(root, source, force=force)
    except Exception as e:
        logger.warning("[IMAGES] Копии для %s не собраны: %s", source, e)
        return 0


def sweep(root: Path) -> int:
    """
    Проходит по всем загруженным фото и досоздаёт недостающие копии.

    Запускается на старте бэкенда: так копии появляются и у фото,
    загруженных до этой функции, и у тех, чья копия не собралась при загрузке.
    Битый файл не повторяется на каждом старте — для него кладётся метка.
    """
    if not root.exists():
        return 0
    written = 0
    for path in root.rglob("*"):
        if path.suffix.lower() not in SOURCE_SUFFIXES or not path.is_file():
            continue
        if path.relative_to(root).parts[0] in VARIANTS:
            continue
        try:
            written += build(root, path)
        except Exception as e:
            logger.warning("[IMAGES] %s пропущен: %s", path, e)
            for variant in VARIANTS:
                base = variant_base(root, variant, path)
                base.parent.mkdir(parents=True, exist_ok=True)
                _with_suffix(base, SKIP_SUFFIX).touch()
    if written:
        logger.info("[IMAGES] Собрано копий фото: %d", written)
    return written
