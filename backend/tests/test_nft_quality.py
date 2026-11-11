import io
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from services import nft_preview as nft

pytestmark = pytest.mark.asyncio
LINK = "https://t.me/nft/WhipCupcake-281261"
ARTWORK = "https://nft.fragment.com/gift/whipcupcake-281261.webp"
THUMB = "https://cdn4.telesco.pe/file/thumb.jpg"


def picture(side, fmt="WEBP"):
    stream = io.BytesIO()
    Image.new("RGB", (side, side), "green").save(stream, fmt)
    return stream.getvalue()


def transport(monkeypatch, *, high=None, low=None, status=200):
    seen = []
    def respond(request):
        url = str(request.url)
        seen.append(url)
        if request.url.host == "t.me":
            return httpx.Response(200, text=f'<meta property="og:title" content="Whip Cupcake #281261"><meta property="og:image" content="{THUMB}">')
        if url == ARTWORK:
            return httpx.Response(status, content=high or b"invalid", headers={"Location":"http://127.0.0.1/private"})
        assert url == THUMB
        return httpx.Response(200, content=low or picture(160, "JPEG"))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(nft.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    return seen


async def test_import_uses_exact_nft_artwork_instead_of_small_og_image(monkeypatch):
    seen = transport(monkeypatch, high=picture(1500))
    content, extension, title = await nft.import_preview(LINK + "/?ignored=http://localhost")
    image = Image.open(io.BytesIO(content))
    assert image.size == (1500, 1500) and image.format == "JPEG"
    assert extension == ".jpg" and title == "Whip Cupcake #281261"
    assert seen == [LINK, ARTWORK]


async def test_unavailable_high_resolution_uses_large_safe_fallback(monkeypatch):
    seen = transport(monkeypatch, status=404, low=picture(800, "PNG"))
    content, _, _ = await nft.import_preview(LINK)
    assert Image.open(io.BytesIO(content)).size == (800, 800)
    assert seen == [LINK, ARTWORK, THUMB]


@pytest.mark.parametrize("status", [200, 302, 404])
async def test_import_never_enlarges_small_thumbnail_or_follows_redirect(monkeypatch, status):
    seen = transport(monkeypatch, high=picture(160), status=status)
    with pytest.raises(ValueError, match="качественное фото"):
        await nft.import_preview(LINK)
    assert seen == [LINK, ARTWORK, THUMB]


async def test_saved_preview_is_bound_to_nft_and_reused_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(nft.settings, "UPLOAD_DIR", str(tmp_path))
    transport(monkeypatch, high=picture(1500))
    url, _ = await nft.save_preview(LINK)
    assert url.startswith("/uploads/giveaways/" + nft.preview_prefix(LINK))
    original = tmp_path / url.removeprefix("/uploads/")
    assert Image.open(original).size == (1500, 1500)
    assert nft.current_preview(LINK, url)
    assert not nft.current_preview("https://t.me/nft/ValentineBox-29850", url)
    fetch = AsyncMock(side_effect=AssertionError("Cached photo must not be fetched again"))
    monkeypatch.setattr(nft, "save_preview", fetch)
    assert await nft.ensure_photo(LINK, url) == url
    fetch.assert_not_awaited()


@pytest.mark.parametrize("old", [None, "/uploads/giveaways/old-160px.jpg", "/uploads/giveaways/unrelated-photo.jpg"])
async def test_old_or_unrelated_nft_photo_is_replaced(monkeypatch, old):
    fetch = AsyncMock(return_value=("/uploads/giveaways/new-nft.jpg", "Gift"))
    monkeypatch.setattr(nft, "save_preview", fetch)
    assert await nft.ensure_photo(LINK, old) == "/uploads/giveaways/new-nft.jpg"
    fetch.assert_awaited_once_with(LINK)


async def test_non_nft_prize_preserves_manual_photo(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(nft, "save_preview", fetch)
    assert await nft.ensure_photo("A manually delivered prize", "/uploads/giveaways/manual.jpg") == "/uploads/giveaways/manual.jpg"
    fetch.assert_not_awaited()
