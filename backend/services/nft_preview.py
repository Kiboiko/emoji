"""Bounded preview import for public Telegram collectible gift links only."""
import asyncio
import hashlib
import io
import re
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlparse
import httpx
from PIL import Image, ImageOps
from services import image_upload, image_variants
from config import settings


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        key = attributes.get("property") or attributes.get("name")
        if tag == "meta" and key in ("og:image", "og:title"):
            self.values[key] = attributes.get("content", "")


def gift_url(value):
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.netloc != "t.me" or not re.fullmatch(r"/nft/[A-Za-z0-9]+-[1-9][0-9]*/?", parsed.path):
        raise ValueError("Нужна ссылка Telegram NFT вида https://t.me/nft/PlushPepe-171")
    return "https://t.me" + parsed.path.rstrip("/")


def image_url(value):
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or not (
        re.fullmatch(r"cdn[0-9]+\.telesco\.pe", host) or host == "nft.fragment.com"
    ):
        raise ValueError("Telegram не предоставил поддерживаемое превью NFT")
    return value


async def read_bounded(client, url, limit):
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("Превью слишком большое")
        return bytes(data)


async def import_preview(link):
    link = gift_url(link)
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False) as client:
        html = await read_bounded(client, link, 1_000_000)
        metadata = Metadata()
        metadata.feed(html.decode("utf-8"))
        # og:image is often only 160px. Fragment serves the actual collectible
        # artwork, including its model and backdrop, at 1500px under this slug.
        slug = urlparse(link).path.rsplit("/", 1)[1].lower()
        candidates = [f"https://nft.fragment.com/gift/{slug}.webp"]
        try:
            candidates.append(image_url(metadata.values.get("og:image", "")))
        except ValueError:
            pass
        for picture in candidates:
            try:
                content = await read_bounded(client, picture, settings.MAX_UPLOAD_SIZE)
                data = await asyncio.to_thread(prepare_photo, content)
                return data, ".jpg", metadata.values.get("og:title", "")[:200]
            except (httpx.HTTPError, ValueError, image_upload.ImageError):
                continue
    raise ValueError("Не удалось получить качественное фото NFT. Попробуйте позже.")


def prepare_photo(content):
    # Apply the existing raster validation/size/metadata policy first. Export
    # the validated original to JPEG for sendPhoto, without enlarging a thumb.
    image_upload.prepare(content, settings.MAX_UPLOAD_SIZE)
    with Image.open(io.BytesIO(content)) as original:
        image = ImageOps.exif_transpose(original)
        if min(image.size) < 512:
            raise ValueError("Фото NFT слишком маленькое")
        image.thumbnail((image_upload.MAX_SIDE, image_upload.MAX_SIDE), Image.Resampling.LANCZOS)
        rgba = image.convert("RGBA")
        photo = Image.new("RGB", rgba.size, "white")
        photo.paste(rgba, mask=rgba.getchannel("A"))
        output = io.BytesIO()
        photo.save(output, "JPEG", quality=95, subsampling=0, optimize=True)
        if output.tell() > min(settings.MAX_UPLOAD_SIZE, 5_000_000):
            raise ValueError("Фото NFT слишком большое для поста")
        return output.getvalue()


def preview_prefix(link):
    identity = hashlib.sha256(gift_url(link).lower().encode()).hexdigest()[:20]
    return f"nft-v2-{identity}-"


def current_preview(link, url):
    prefix = "/uploads/giveaways/" + preview_prefix(link)
    if not url or not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}\.jpg", url):
        return False
    path = Path(settings.UPLOAD_DIR) / "giveaways" / url.rsplit("/", 1)[1]
    try:
        with Image.open(path) as image:
            return image.format == "JPEG" and min(image.size) >= 512
    except (OSError, ValueError):
        return False


async def ensure_photo(prize, photo_url):
    if not prize.strip().startswith("https://t.me/nft/"):
        return photo_url
    if await asyncio.to_thread(current_preview, prize, photo_url):
        return photo_url
    try:
        url, _ = await save_preview(prize)
        return url
    except Exception:
        raise ValueError("Не удалось загрузить качественное фото NFT. Проверьте ссылку на подарок и повторите попытку.") from None


async def save_preview(link):
    """Store the original and local variants together before returning its URL."""
    data, extension, title = await import_preview(link)
    filename = preview_prefix(link) + uuid4().hex + extension
    folder = Path(settings.UPLOAD_DIR) / "giveaways"
    def save():
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / filename
        target.write_bytes(data)
        image_variants.build_quietly(Path(settings.UPLOAD_DIR), target)
    await asyncio.to_thread(save)
    return "/uploads/giveaways/" + filename, title
