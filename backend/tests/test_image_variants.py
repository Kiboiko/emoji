"""
Облегчённые копии фото: каталог грузил оригиналы PNG по 2–4 МБ и тормозил на
телефоне. Оригинал остаётся как есть, рядом — копии, которые nginx отдаёт по
тому же адресу.
"""

import os
import random

from PIL import Image

from services import image_variants


def _noisy(size, mode="RGB") -> Image.Image:
    # Шум, а не заливка: однотонный PNG сжимается в сотни байт, и копия
    # оказалась бы не легче оригинала
    data = random.Random(7).randbytes(size[0] * size[1] * len(mode))
    return Image.frombytes(mode, size, data)


def _save(root, rel, image, fmt, **options):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, fmt, **options)
    return path


def _copy(root, variant, rel, suffix):
    return root / variant / "uploads" / f"{rel}{suffix}"


def test_heavy_png_gets_light_webp_copies(tmp_path):
    source = _save(tmp_path, "listings/a.png", _noisy((1600, 1200)), "PNG")

    assert image_variants.build(tmp_path, source) == 3

    web = _copy(tmp_path, "_web", "listings/a.png", ".v3.webp")
    thumb = _copy(tmp_path, "_thumb", "listings/a.png", ".v3.webp")
    with Image.open(web) as image:
        assert image.format == "WEBP" and image.size == (1024, 768)
    with Image.open(thumb) as image:
        assert image.size == (384, 288)
    with Image.open(_copy(tmp_path, "_cart", "listings/a.png", ".v3.webp")) as image:
        assert image.size == (160, 120)
    assert thumb.stat().st_size < web.stat().st_size < source.stat().st_size
    # Оригинал не тронут: на него ссылаются товары и сделки
    with Image.open(source) as image:
        assert image.format == "PNG" and image.size == (1600, 1200)


def test_transparent_png_keeps_transparency_in_webp(tmp_path):
    picture = _noisy((900, 900), "RGBA")
    picture.putalpha(0)
    source = _save(tmp_path, "stores/logo.png", picture, "PNG")

    image_variants.build(tmp_path, source)

    thumb = _copy(tmp_path, "_thumb", "stores/logo.png", ".v3.webp")
    with Image.open(thumb) as image:
        assert image.format == "WEBP" and image.mode == "RGBA"
    assert not _copy(tmp_path, "_thumb", "stores/logo.png", ".jpg").exists()


def test_copy_not_lighter_than_original_is_skipped(tmp_path):
    # Маленький и уже сильно сжатый JPEG: копия была бы не легче, nginx
    # отдаст оригинал
    source = _save(tmp_path, "channels/1.jpg", _noisy((300, 300)), "JPEG", quality=40)

    assert image_variants.build(tmp_path, source) == 1
    assert _copy(tmp_path, "_thumb", "channels/1.jpg", ".v3.skip").exists()
    assert not _copy(tmp_path, "_thumb", "channels/1.jpg", ".jpg").exists()
    # Метка запомнена: второй проход файл не трогает
    assert image_variants.build(tmp_path, source) == 0


def test_overwritten_source_gets_fresh_copies(tmp_path):
    # Аватар канала перезаписывается под тем же именем: копия от прошлой
    # картинки отдавалась бы вместо новой
    source = _save(tmp_path, "channels/2.png", _noisy((1000, 1000)), "PNG")
    image_variants.build(tmp_path, source)
    web = _copy(tmp_path, "_web", "channels/2.png", ".v3.webp")
    stale = web.stat().st_mtime - 60
    os.utime(web, (stale, stale))
    os.utime(_copy(tmp_path, "_thumb", "channels/2.png", ".v3.webp"), (stale, stale))

    assert image_variants.build(tmp_path, source) == 2
    assert web.stat().st_mtime >= source.stat().st_mtime


def test_sweep_builds_missing_copies_and_skips_its_own_output(tmp_path):
    _save(tmp_path, "listings/b.png", _noisy((800, 800)), "PNG")
    (tmp_path / "listings" / "broken.png").write_bytes(b"not an image")

    assert image_variants.sweep(tmp_path) == 3
    # Повторный проход: копии свежие, а сами копии за исходники не считаются
    assert image_variants.sweep(tmp_path) == 0
    # Битый файл получил метку и не пережимается на каждом старте
    assert _copy(tmp_path, "_web", "listings/broken.png", ".v3.skip").exists()
