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
    for path in ("/api/admin/p2p/listings", "/api/admin/staff/moderators", "/api/admin/settings"):
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
