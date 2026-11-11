"""
Сквозная проверка по HTTP: зависимости, права и заголовки.

Остальные тесты вызывают функции маршрутов напрямую и подставляют
пользователя сами — они не видят, что FastAPI на самом деле подключил к
маршруту. Здесь запросы идут через приложение целиком, как с клиента:
проверяется, что модератору закрыты разделы администратора, что заголовок
пагинации доезжает, что удалённый вход действительно удалён.
"""

import uuid
from decimal import Decimal

import httpx
import pytest

from config import settings
from models.category import Category
from models.product import Product
from models.user import User
from utils import auth

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client(db, tmp_path, monkeypatch):
    # StaticFiles требует существующий каталог загрузок уже при импорте
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    import main
    from database import get_db

    async def override():
        yield db

    main.app.dependency_overrides[get_db] = override
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    main.app.dependency_overrides.clear()


def _bearer(user: User, **extra) -> dict:
    token = auth.create_access_token({
        "user_id": str(user.id), "sub": user.username,
        "is_admin": user.is_admin, "tv": user.token_version, **extra,
    })
    return {"Authorization": f"Bearer {token}"}


async def test_telegram_login_preflight_accepts_init_data_only_from_allowed_origins(client):
    from main import origins

    headers = {
        "Origin": origins[0],
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,x-telegram-init-data",
    }
    response = await client.options("/api/auth/telegram", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origins[0]
    assert "x-telegram-init-data" in response.headers["access-control-allow-headers"].lower()

    response = await client.options("/api/auth/telegram", headers={**headers, "Origin": "https://untrusted.example"})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.fixture
async def staff(db, user_factory):
    admin = await user_factory(username="wire_admin", is_admin=True)
    moderator = await user_factory(username="wire_mod", is_moderator=True)
    stranger = await user_factory(username="wire_user")
    return admin, moderator, stranger


async def test_moderator_reaches_only_the_moderator_sections(client, staff):
    admin, moderator, _ = staff
    mod = _bearer(moderator, role="moderator")

    allowed = [
        "/api/admin/p2p/listings", "/api/admin/p2p/deals",
        "/api/admin/subscriptions/channel-photos",
    ]
    for path in allowed:
        assert (await client.get(path, headers=mod)).status_code == 200, path

    forbidden = [
        "/api/admin/staff/moderators", "/api/admin/staff/audit-log",
        "/api/admin/staff/login-log", "/api/admin/settings", "/api/admin/p2p/sellers",
        "/api/admin/finance/accounts", "/api/admin/users", "/api/admin/orders",
        "/api/admin/stats", "/api/withdrawals/admin/all",
    ]
    for path in forbidden:
        assert (await client.get(path, headers=mod)).status_code == 403, path

    # Администратору всё открыто
    adm = _bearer(admin, role="admin")
    for path in allowed + ["/api/admin/staff/moderators", "/api/admin/staff/audit-log"]:
        assert (await client.get(path, headers=adm)).status_code == 200, path


async def test_regular_user_is_refused_everywhere_in_the_panel(client, staff):
    _, _, stranger = staff
    headers = _bearer(stranger)
    for path in ("/api/admin/p2p/listings", "/api/admin/staff/moderators", "/api/admin/settings", "/api/admin/subscriptions/channel-photos"):
        assert (await client.get(path, headers=headers)).status_code == 403, path
    assert (await client.get("/api/admin/p2p/listings")).status_code == 401


async def test_moderator_cannot_use_admin_actions(client, staff):
    _, moderator, _ = staff
    mod = _bearer(moderator, role="moderator")

    created = await client.post(
        "/api/admin/staff/moderators", headers=mod,
        json={"username": "sneaky_mod", "password": "Correct-Horse-77"},
    )
    verify = await client.post(
        f"/api/admin/p2p/sellers/{uuid.uuid4()}/verify", headers=mod, json={"verified": True},
    )
    setting = await client.put(
        "/api/admin/settings/p2p_auto_publish_verified", headers=mod, json={"value": True},
    )

    assert created.status_code == verify.status_code == setting.status_code == 403


async def test_revoked_token_is_rejected_over_http(client, staff, db):
    admin, _, _ = staff
    headers = _bearer(admin, role="admin")
    assert (await client.get("/api/admin/staff/moderators", headers=headers)).status_code == 200

    admin.token_version = 1
    await db.flush()

    response = await client.get("/api/admin/staff/moderators", headers=headers)
    assert response.status_code == 401


ADMIN_SECTIONS_WITH_OWN_DEPENDENCY = (
    "/api/admin/stats", "/api/admin/stats/attention", "/api/admin/stats/conversion",
    "/api/admin/users", "/api/admin/orders", "/api/admin/orders/processing",
)


async def test_revoked_admin_token_is_rejected_in_stats_users_and_orders(client, staff, db):
    """Эти разделы когда-то имели свою проверку токена без сверки версии."""
    admin, _, _ = staff
    headers = _bearer(admin, role="admin")
    for path in ADMIN_SECTIONS_WITH_OWN_DEPENDENCY:
        assert (await client.get(path, headers=headers)).status_code == 200, path

    admin.token_version = 1  # смена пароля или «Выйти везде»
    await db.flush()

    for path in ADMIN_SECTIONS_WITH_OWN_DEPENDENCY:
        assert (await client.get(path, headers=headers)).status_code == 401, path
    block = await client.post(f"/api/admin/users/{uuid.uuid4()}/block", headers=headers, json={})
    complete = await client.post(f"/api/admin/orders/{uuid.uuid4()}/complete", headers=headers)
    assert block.status_code == complete.status_code == 401


async def test_blocked_admin_is_refused_in_stats_users_and_orders(client, staff, db):
    admin, _, _ = staff
    headers = _bearer(admin, role="admin")
    admin.is_blocked = True
    await db.flush()

    for path in ADMIN_SECTIONS_WITH_OWN_DEPENDENCY:
        assert (await client.get(path, headers=headers)).status_code == 403, path


def _api_routes(app):
    """Все маршруты, включая вложенные роутеры (в новых FastAPI они лежат в _IncludedRouter)."""
    from fastapi.routing import APIRoute

    for r in app.routes:
        if isinstance(r, APIRoute):
            yield "", r
        elif hasattr(r, "original_router"):
            prefix = getattr(getattr(r, "include_context", None), "prefix", "") or ""
            for inner in r.original_router.routes:
                if isinstance(inner, APIRoute):
                    yield prefix, inner


def _dependency_calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependency_calls(dep)


async def test_every_admin_route_goes_through_the_shared_staff_check():
    """
    Забытая или самодельная защита на новом админском маршруте — главный способ
    дыры. Любой адрес с /admin обязан зависеть от require_admin или
    require_staff; открытыми остаются только вход, обновление и выход.
    """
    import main

    public = {"/api/admin/auth/login", "/api/admin/auth/refresh", "/api/admin/auth/logout"}
    routes = list(_api_routes(main.app))
    assert len(routes) > 100, "обход не нашёл маршрутов: проверка стала бы пустой"

    unguarded, admin_routes = [], 0
    for prefix, route in routes:
        path = prefix + route.path
        if "/admin" not in path or path in public:
            continue
        admin_routes += 1
        calls = set(_dependency_calls(route.dependant))
        if auth.require_admin not in calls and auth.require_staff not in calls:
            unguarded.append(path)

    assert admin_routes > 40
    assert unguarded == []


async def test_old_admin_login_endpoint_is_gone(client):
    response = await client.post(
        "/api/auth/admin", json={"username": "admin", "password": "whatever"},
    )
    assert response.status_code in (404, 405)


async def test_login_endpoint_works_end_to_end_and_sets_cookie(client, db, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "e2e_boss")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "e2e-password-123")

    bad = await client.post(
        "/api/admin/auth/login", json={"username": "e2e_boss", "password": "nope-nope-nope"},
    )
    good = await client.post(
        "/api/admin/auth/login", json={"username": "e2e_boss", "password": "e2e-password-123"},
    )

    assert bad.status_code == 401
    assert good.status_code == 200 and good.json()["role"] == "admin"
    assert "admin_refresh_token" in good.headers["set-cookie"]
    me = await client.get(
        "/api/admin/auth/me", headers={"Authorization": f"Bearer {good.json()['access_token']}"},
    )
    assert me.status_code == 200 and me.json()["role"] == "admin"


async def test_catalog_pagination_header_reaches_the_client(client, db):
    category = Category(id=uuid.uuid4(), name_ru="Разное", name_en="Misc")
    db.add(category)
    await db.flush()
    for n in range(5):
        db.add(Product(
            id=uuid.uuid4(), name_ru=f"Товар {n}", name_en=f"Item {n}",
            description_ru="описание", description_en="description",
            price_usdt=Decimal("1.00"), image_url="/uploads/products/placeholder.png",
            category_id=category.id, type="service", content_data={},
        ))
    await db.flush()

    first = await client.get("/api/products", params={"limit": 2, "skip": 0})
    last = await client.get("/api/products", params={"limit": 2, "skip": 4})
    everything = await client.get("/api/products", params={"limit": 100})

    assert first.status_code == 200 and len(first.json()) == 2
    assert first.headers["x-has-more"] == "1"
    assert len(last.json()) == 1 and last.headers["x-has-more"] == "0"
    assert len(everything.json()) == 5 and everything.headers["x-has-more"] == "0"


async def test_terms_language_parameter_over_http(client, db):
    from services import settings_service
    await settings_service.set_setting(db, "terms_text", "Русский текст")
    await settings_service.set_setting(db, "terms_text_en", "English text")

    ru = await client.get("/api/terms", params={"lang": "ru"})
    en = await client.get("/api/terms", params={"lang": "en"})

    assert ru.json()["text"] == "Русский текст"
    assert en.json()["text"] == "English text" and en.json()["language"] == "en"


@pytest.mark.parametrize("first_kind", ["avatar", "cover"])
async def test_moderator_removes_channel_photos_everywhere(client, db, staff, tmp_path, monkeypatch, first_kind):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from models.subscription import Channel, ChannelStatus, SubscriptionPlan
    from models.admin_log import AdminAuditLog
    from routes import admin_subscriptions

    admin, moderator, stranger = staff
    headers = _bearer(moderator, role="moderator")
    sent = AsyncMock()
    monkeypatch.setattr(admin_subscriptions.telegram_service, "send_message", sent)
    category = Category(id=uuid.uuid4(), name_ru="Подписки", name_en="Subscriptions")
    db.add(category)
    await db.flush()
    channel = Channel(
        id=uuid.uuid4(), owner_user_id=admin.id, title="Канал", telegram_chat_id=-100555,
        status=ChannelStatus.ACTIVE, avatar_url="/uploads/channels/avatar.jpg?v=123",
        cover_url="/uploads/channels/cover.jpg", payout_wallet="private-wallet",
    )
    product = Product(
        id=uuid.uuid4(), name_ru="Тариф", name_en="Plan", description_ru="d", description_en="d",
        price_usdt=Decimal("1"), image_url=channel.cover_url, category_id=category.id,
        type="subscription", content_data={},
    )
    db.add_all([channel, product])
    await db.flush()
    db.add(SubscriptionPlan(
        channel_id=channel.id, product_id=product.id, title_ru="Месяц", title_en="Month",
        duration_days=30, price_usd=Decimal("1"),
    ))
    await db.flush()
    for name in ("avatar.jpg", "cover.jpg"):
        for rel in (f"channels/{name}", f"_web/uploads/channels/{name}.jpg", f"_thumb/uploads/channels/{name}.jpg"):
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"photo")
    page = await client.get("/api/admin/subscriptions/channel-photos", headers=headers)
    assert page.status_code == 200
    assert set(page.json()["items"][0]) == {"id", "title", "avatar_url", "cover_url"}
    for kind in (first_kind, "cover" if first_kind == "avatar" else "avatar"):
        path = f"/api/admin/subscriptions/channels/{channel.id}/photos/{kind}"
        assert (await client.delete(path)).status_code == 401
        assert (await client.delete(path, headers=_bearer(stranger))).status_code == 403
        assert (await client.delete(path, headers=headers)).status_code == 200
        await db.refresh(channel)
        await db.refresh(product)
        assert getattr(channel, f"{kind}_url") is None
        assert product.image_url == (channel.cover_url or channel.avatar_url or "/uploads/products/placeholder.png")
        assert not (tmp_path / f"channels/{kind}.jpg").exists()
        assert not (tmp_path / f"_web/uploads/channels/{kind}.jpg.jpg").exists()
        assert not (tmp_path / f"_thumb/uploads/channels/{kind}.jpg.jpg").exists()
        assert (await client.delete(path, headers=headers)).status_code == 400
    assert sent.await_count == 2
    entries = (await db.execute(select(AdminAuditLog).where(AdminAuditLog.target_id == str(channel.id)))).scalars().all()
    assert {e.details["kind"] for e in entries} == {"channel_avatar", "channel_cover"}
    assert all(e.actor_role == "moderator" for e in entries)
    missing = f"/api/admin/subscriptions/channels/{uuid.uuid4()}/photos/avatar"
    assert (await client.delete(missing, headers=headers)).status_code == 404
    invalid = f"/api/admin/subscriptions/channels/{channel.id}/photos/invalid"
    assert (await client.delete(invalid, headers=headers)).status_code == 422


@pytest.mark.parametrize("reference", ["same_channel", "other_channel", "product", "gallery", "listing", "seller"])
async def test_channel_photo_deletion_preserves_shared_file(client, db, staff, tmp_path, monkeypatch, reference):
    from unittest.mock import AsyncMock
    from models.subscription import Channel
    from models.p2p import ListingImage, ProductListing, SellerProfile
    from routes import admin_subscriptions

    admin, moderator, _ = staff
    monkeypatch.setattr(admin_subscriptions.telegram_service, "send_message", AsyncMock())
    url = "/uploads/channels/shared.jpg"
    channel = Channel(owner_user_id=admin.id, title="Канал", telegram_chat_id=-100556,
                      avatar_url=url + "?v=1")
    db.add(channel)
    if reference == "same_channel":
        channel.cover_url = url + "?v=2"
    elif reference == "other_channel":
        db.add(Channel(owner_user_id=admin.id, title="Другой канал", telegram_chat_id=-100557,
                       avatar_url=url + "?v=2"))
    elif reference in ("product", "gallery"):
        category = Category(id=uuid.uuid4(), name_ru="Товары", name_en="Products")
        db.add(category)
        await db.flush()
        db.add(Product(name_ru="Товар", name_en="Product", description_ru="d", description_en="d",
                       price_usdt=Decimal("1"), category_id=category.id, type="service", content_data={},
                       image_url=url if reference == "product" else "/uploads/products/placeholder.png",
                       images=[url + "?v=2"] if reference == "gallery" else []))
    else:
        seller = SellerProfile(user_id=admin.id, display_name="Магазин", payout_wallet="",
                               avatar_url=url if reference == "seller" else None)
        db.add(seller)
        await db.flush()
        if reference == "listing":
            listing = ProductListing(seller_id=seller.id, name="Товар", description="Описание",
                                     price_usd=Decimal("1"))
            db.add(listing)
            await db.flush()
            db.add(ListingImage(listing_id=listing.id, url=url + "?v=2"))
    await db.flush()
    paths = [tmp_path / rel for rel in ("channels/shared.jpg", "_web/uploads/channels/shared.jpg.jpg", "_thumb/uploads/channels/shared.jpg.jpg")]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"shared")
    response = await client.delete(f"/api/admin/subscriptions/channels/{channel.id}/photos/avatar",
                                   headers=_bearer(moderator, role="moderator"))
    assert response.status_code == 200
    await db.refresh(channel)
    assert channel.avatar_url is None
    assert all(path.exists() for path in paths)
