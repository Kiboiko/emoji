"""
Защита админки и модераторы.

Главное, что проверяется:
  * смена пароля и «выйти везде» убивают токены — в том числе украденные;
  * после смены пароля пароль из .env больше не открывает вход;
  * модератор не попадает в разделы администратора, но работает с заявками;
  * каждая попытка входа и каждое действие персонала остаются в журнале.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy import select

from config import settings
from models.admin_log import AdminAuditLog, AdminLoginLog
from models.category import Category
from models.p2p import ListingImage, ListingStatus, ProductListing, SellerProfile
from models.product import Product
from models.user import User
from routes import admin_auth, admin_p2p, admin_staff
from routes import auth as app_auth_routes
from schemas.auth import AdminLogin
from services import image_variants
from services.telegram_service import telegram_service
from utils import auth

pytestmark = pytest.mark.asyncio

ENV_USER = "boss_env"
ENV_PASSWORD = "env-password-for-tests-1"
GOOD_PASSWORD = "Correct-Horse-77"


@pytest.fixture(autouse=True)
def env_credentials(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USERNAME", ENV_USER)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", ENV_PASSWORD)
    admin_auth._login_attempts.clear()
    yield
    admin_auth._login_attempts.clear()


def _request(ip="203.0.113.7", agent="pytest-browser") -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/", "client": ("127.0.0.1", 1),
        "headers": [
            (b"user-agent", agent.encode()),
            (b"x-forwarded-for", ip.encode()),
        ],
    })


async def _login(db, username, password, **kwargs):
    return await admin_auth.login(
        AdminLogin(username=username, password=password),
        _request(**kwargs), Response(), db=db,
    )


async def _user_of(db, token: str) -> User:
    return await auth.get_current_user(authorization=f"Bearer {token}", db=db)


async def _log(db):
    return (await db.execute(
        select(AdminLoginLog).order_by(AdminLoginLog.created_at)
    )).scalars().all()


@pytest.fixture
async def admin(db):
    row = User(
        id=uuid.uuid4(), telegram_id=777000, username=ENV_USER, first_name="Administrator",
        is_admin=True, referral_code="admin-test",
    )
    db.add(row)
    await db.flush()
    return row


async def _make_moderator(db, admin, username="mod_anna", password=GOOD_PASSWORD):
    return await admin_staff.create_moderator(
        admin_staff.ModeratorCreate(username=username, password=password, display_name="Анна"),
        admin=admin, db=db,
    )


# ---------------------------------------------------------------------------
# Вход и журнал входов
# ---------------------------------------------------------------------------

async def test_env_password_logs_in_and_is_journaled(db, admin):
    result = await _login(db, ENV_USER, ENV_PASSWORD)

    assert result["role"] == "admin"
    entry = (await _log(db))[-1]
    assert entry.success is True and entry.username == ENV_USER
    assert entry.ip == "203.0.113.7" and entry.user_agent == "pytest-browser"
    # Пароль в журнал не попадает ни в каком виде
    assert ENV_PASSWORD not in repr(vars(entry))


async def test_wrong_password_is_journaled_with_reason(db, admin):
    with pytest.raises(HTTPException) as exc:
        await _login(db, ENV_USER, "wrong-password-xx")
    assert exc.value.status_code == 401

    entry = (await _log(db))[-1]
    assert entry.success is False and entry.reason == "bad_password"


async def test_unknown_login_is_journaled(db, admin):
    with pytest.raises(HTTPException) as exc:
        await _login(db, "nobody", "whatever-password")
    assert exc.value.status_code == 401
    assert (await _log(db))[-1].reason == "unknown_user"


async def test_failed_attempts_are_limited_per_ip_and_journaled(db, admin):
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        with pytest.raises(HTTPException):
            await _login(db, ENV_USER, "wrong-password-xx")

    with pytest.raises(HTTPException) as exc:
        await _login(db, ENV_USER, ENV_PASSWORD)     # верный пароль, но лимит
    assert exc.value.status_code == 429
    assert (await _log(db))[-1].reason == "rate_limited"

    # С другого адреса — можно: лимит не общий на всех
    assert (await _login(db, ENV_USER, ENV_PASSWORD, ip="198.51.100.9"))["role"] == "admin"


async def test_login_issues_staff_token_with_version(db, admin):
    result = await _login(db, ENV_USER, ENV_PASSWORD)
    payload = auth.decode_access_token(result["access_token"])

    assert payload["role"] == "admin" and payload["is_admin"] is True
    assert payload["tv"] == 0


# ---------------------------------------------------------------------------
# Смена пароля, «выйти везде»
# ---------------------------------------------------------------------------

async def test_password_change_kills_tokens_and_env_password(db, admin):
    first = await _login(db, ENV_USER, ENV_PASSWORD)
    me = await _user_of(db, first["access_token"])

    await admin_auth.change_password(
        admin_auth.PasswordChange(current_password=ENV_PASSWORD, new_password=GOOD_PASSWORD),
        Response(), user=me, db=db,
    )

    # Старый токен — украденный или свой — больше не работает
    with pytest.raises(HTTPException) as exc:
        await _user_of(db, first["access_token"])
    assert exc.value.status_code == 401

    # Пароль из .env больше не открывает вход: иначе смена пароля ничего бы
    # не закрывала
    with pytest.raises(HTTPException):
        await _login(db, ENV_USER, ENV_PASSWORD)

    # Новый пароль работает, и токен по нему рабочий
    second = await _login(db, ENV_USER, GOOD_PASSWORD)
    assert (await _user_of(db, second["access_token"])).id == admin.id


async def test_password_change_demands_the_current_password(db, admin):
    me = admin
    with pytest.raises(HTTPException) as exc:
        await admin_auth.change_password(
            admin_auth.PasswordChange(current_password="not-my-password", new_password=GOOD_PASSWORD),
            Response(), user=me, db=db,
        )
    assert exc.value.status_code == 400


@pytest.mark.parametrize("weak", ["short1", "aaaaaaaaaaaa", "1111122222"])
async def test_weak_new_password_is_refused(db, admin, weak):
    with pytest.raises(HTTPException) as exc:
        await admin_auth.change_password(
            admin_auth.PasswordChange(current_password=ENV_PASSWORD, new_password=weak),
            Response(), user=admin, db=db,
        )
    assert exc.value.status_code == 400


async def test_too_long_password_is_refused_not_truncated(db, admin):
    with pytest.raises(HTTPException) as exc:
        await admin_auth.change_password(
            admin_auth.PasswordChange(
                current_password=ENV_PASSWORD, new_password="Ab1-" * 30,
            ),
            Response(), user=admin, db=db,
        )
    assert exc.value.status_code == 400


async def test_logout_all_revokes_every_token(db, admin):
    one = await _login(db, ENV_USER, ENV_PASSWORD)
    two = await _login(db, ENV_USER, ENV_PASSWORD, ip="198.51.100.9")
    me = await _user_of(db, one["access_token"])

    await admin_auth.logout_all(Response(), user=me, db=db)

    for token in (one, two):
        with pytest.raises(HTTPException) as exc:
            await _user_of(db, token["access_token"])
        assert exc.value.status_code == 401
    # Пароль прежний — войти заново можно
    assert (await _login(db, ENV_USER, ENV_PASSWORD))["role"] == "admin"


async def test_legacy_admin_token_without_version_is_revoked_too(db, admin):
    """Токен, выданный до появления версии, не должен пережить сброс."""
    legacy = auth.create_access_token(
        {"user_id": str(admin.id), "sub": ENV_USER, "is_admin": True}
    )
    assert (await _user_of(db, legacy)).id == admin.id      # версия 0 — рабочий

    admin.token_version = 1
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await _user_of(db, legacy)
    assert exc.value.status_code == 401


async def test_app_token_is_not_subject_to_staff_versioning(db, user_factory):
    """Токен Telegram-приложения версии не несёт и сбросом не затрагивается."""
    user = await user_factory(username="app_admin_like", is_admin=True)
    token = auth.create_access_token({
        "user_id": str(user.id), "telegram_id": user.telegram_id, "is_admin": user.is_admin,
    })
    user.token_version = 5
    await db.flush()

    assert (await _user_of(db, token)).id == user.id


async def test_refresh_is_revoked_with_the_session(db, admin):
    response = Response()
    await admin_auth.login(
        AdminLogin(username=ENV_USER, password=ENV_PASSWORD), _request(), response, db=db,
    )
    cookie = response.headers["set-cookie"].split("admin_refresh_token=")[1].split(";")[0]

    def refresh_request():
        req = _request()
        req.scope["headers"].append((b"cookie", f"admin_refresh_token={cookie}".encode()))
        return req

    ok = await admin_auth.refresh_token(refresh_request(), Response(), db=db)
    assert ok["role"] == "admin"

    await admin_auth.logout_all(Response(), user=admin, db=db)
    with pytest.raises(HTTPException) as exc:
        await admin_auth.refresh_token(refresh_request(), Response(), db=db)
    assert exc.value.status_code == 401


async def test_second_admin_login_endpoint_is_gone():
    """POST /api/auth/admin обходил бы и лимит, и смену пароля."""
    assert not hasattr(app_auth_routes, "authenticate_admin")


# ---------------------------------------------------------------------------
# Модераторы
# ---------------------------------------------------------------------------

async def test_moderator_logs_in_with_own_credentials(db, admin):
    created = await _make_moderator(db, admin)
    assert created["active"] is True

    result = await _login(db, "mod_anna", GOOD_PASSWORD)

    assert result["role"] == "moderator"
    payload = auth.decode_access_token(result["access_token"])
    assert payload["is_admin"] is False and payload["role"] == "moderator"


async def test_moderator_is_kept_out_of_admin_sections(db, admin):
    await _make_moderator(db, admin)
    result = await _login(db, "mod_anna", GOOD_PASSWORD)
    moderator = await _user_of(db, result["access_token"])

    with pytest.raises(HTTPException) as exc:
        await auth.require_admin(user=moderator)
    assert exc.value.status_code == 403
    # Но в общие разделы пускает
    assert (await auth.require_staff(user=moderator)).id == moderator.id


async def test_regular_user_is_not_staff(db, user_factory):
    user = await user_factory(username="just_a_user")
    with pytest.raises(HTTPException) as exc:
        await auth.require_staff(user=user)
    assert exc.value.status_code == 403


async def test_moderator_login_collisions_are_refused(db, admin, user_factory):
    await user_factory(username="taken_name")
    with pytest.raises(HTTPException) as exc:
        await _make_moderator(db, admin, username="Taken_Name")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException):
        await _make_moderator(db, admin, username=ENV_USER)

    await _make_moderator(db, admin, username="mod_one")
    with pytest.raises(HTTPException):
        await _make_moderator(db, admin, username="MOD_ONE")


@pytest.mark.parametrize("bad", ["ab", "name with space", "имя-кириллица", "a" * 33])
async def test_moderator_login_format(db, admin, bad):
    # Слишком короткий и слишком длинный отсекает схема, остальное — проверка
    # формата в обработчике
    with pytest.raises((HTTPException, ValidationError)) as exc:
        await _make_moderator(db, admin, username=bad)
    if isinstance(exc.value, HTTPException):
        assert exc.value.status_code == 400


async def test_moderator_without_password_cannot_log_in(db, admin):
    created = await _make_moderator(db, admin)
    moderator = await db.get(User, uuid.UUID(created["id"]))
    moderator.hashed_password = None
    await db.flush()

    # Пароль из .env — только для администратора
    with pytest.raises(HTTPException):
        await _login(db, "mod_anna", ENV_PASSWORD)
    with pytest.raises(HTTPException):
        await _login(db, "mod_anna", "")


async def test_admin_resets_moderator_password_and_sessions(db, admin):
    created = await _make_moderator(db, admin)
    old = await _login(db, "mod_anna", GOOD_PASSWORD)

    await admin_staff.reset_moderator_password(
        uuid.UUID(created["id"]), admin_staff.PasswordReset(password="Brand-New-Pass-9"),
        admin=admin, db=db,
    )

    with pytest.raises(HTTPException):
        await _user_of(db, old["access_token"])
    with pytest.raises(HTTPException):
        await _login(db, "mod_anna", GOOD_PASSWORD)
    assert (await _login(db, "mod_anna", "Brand-New-Pass-9"))["role"] == "moderator"


async def test_suspended_moderator_cannot_work_until_restored(db, admin):
    created = await _make_moderator(db, admin)
    token = (await _login(db, "mod_anna", GOOD_PASSWORD))["access_token"]
    mid = uuid.UUID(created["id"])

    await admin_staff.set_moderator_active(
        mid, admin_staff.ActiveToggle(active=False), admin=admin, db=db,
    )
    with pytest.raises(HTTPException):
        await _login(db, "mod_anna", GOOD_PASSWORD)
    with pytest.raises(HTTPException):
        await _user_of(db, token)
    assert (await _log(db))[-1].reason == "blocked"

    await admin_staff.set_moderator_active(
        mid, admin_staff.ActiveToggle(active=True), admin=admin, db=db,
    )
    assert (await _login(db, "mod_anna", GOOD_PASSWORD))["role"] == "moderator"


async def test_removed_moderator_loses_access_but_history_stays(db, admin):
    created = await _make_moderator(db, admin)
    token = (await _login(db, "mod_anna", GOOD_PASSWORD))["access_token"]
    mid = uuid.UUID(created["id"])

    await admin_staff.remove_moderator(mid, admin=admin, db=db)

    with pytest.raises(HTTPException):
        await _login(db, "mod_anna", GOOD_PASSWORD)
    with pytest.raises(HTTPException):
        await _user_of(db, token)
    # Учётка осталась: на неё ссылаются решения и журнал
    row = await db.get(User, mid)
    assert row is not None and row.is_moderator is False


async def test_admin_cannot_be_managed_as_a_moderator(db, admin):
    with pytest.raises(HTTPException) as exc:
        await admin_staff.reset_moderator_password(
            admin.id, admin_staff.PasswordReset(password="Brand-New-Pass-9"),
            admin=admin, db=db,
        )
    assert exc.value.status_code == 404


async def test_moderator_list_shows_last_login_and_actions(db, admin):
    await _make_moderator(db, admin)
    await _login(db, "mod_anna", GOOD_PASSWORD)

    listed = await admin_staff.list_moderators(admin=admin, db=db)

    assert [m["username"] for m in listed] == ["mod_anna"]
    assert listed[0]["last_login"] is not None
    assert listed[0]["display_name"] == "Анна"


# ---------------------------------------------------------------------------
# Работа модератора и журнал действий
# ---------------------------------------------------------------------------

@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Игры", name_en="Games")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def pending(db, user_factory, category):
    seller_user = await user_factory(username="staff_seller")
    profile = SellerProfile(
        id=uuid.uuid4(), user_id=seller_user.id, display_name="Staff Shop",
        payout_wallet="UQWallet1234567890", avatar_url="/uploads/stores/logo.png",
    )
    db.add(profile)
    await db.flush()
    listing = ProductListing(
        id=uuid.uuid4(), seller_id=profile.id, category_id=category.id,
        name="Клавиатура", name_en="Keyboard", description="Механическая, почти новая",
        description_en="Mechanical, almost new", price_usd=Decimal("50.00"),
        status=ListingStatus.PENDING,
    )
    db.add(listing)
    await db.flush()
    for order, name in enumerate(("a.png", "b.png")):
        db.add(ListingImage(
            id=uuid.uuid4(), listing_id=listing.id,
            url=f"/uploads/listings/{name}", sort_order=order,
        ))
    await db.flush()
    await db.refresh(listing, ["images", "seller"])
    return listing


async def _moderator_user(db, admin):
    await _make_moderator(db, admin)
    result = await _login(db, "mod_anna", GOOD_PASSWORD)
    return await _user_of(db, result["access_token"])


async def _audit(db):
    return (await db.execute(
        select(AdminAuditLog).order_by(AdminAuditLog.created_at)
    )).scalars().all()


async def test_moderator_approves_and_it_is_journaled(db, admin, pending):
    moderator = await _moderator_user(db, admin)

    with patch.object(telegram_service, "send_message", AsyncMock()):
        await admin_p2p.moderate_listing(
            pending.id, admin_p2p.ModerationDecision(approve=True, comment="ок"),
            admin=moderator, db=db,
        )

    await db.refresh(pending)
    assert pending.status == ListingStatus.APPROVED
    assert pending.moderator_id == moderator.id
    entry = [e for e in await _audit(db) if e.action == "listing.approve"][-1]
    assert entry.actor_role == "moderator" and entry.actor_name == "mod_anna"
    assert entry.target_id == str(pending.id)
    assert entry.details["name"] == "Клавиатура" and entry.details["comment"] == "ок"


async def test_rejection_is_journaled_with_the_reason(db, admin, pending):
    moderator = await _moderator_user(db, admin)

    with patch.object(telegram_service, "send_message", AsyncMock()):
        await admin_p2p.moderate_listing(
            pending.id, admin_p2p.ModerationDecision(approve=False, comment="Нечёткое фото"),
            admin=moderator, db=db,
        )

    entry = [e for e in await _audit(db) if e.action == "listing.reject"][-1]
    assert entry.details["comment"] == "Нечёткое фото"


async def test_moderator_dispute_actions_are_journaled(db, admin, pending, order_factory, user_factory):
    from models.p2p import Deal, DealStatus
    moderator = await _moderator_user(db, admin)
    buyer = await user_factory(username="dispute_buyer")
    order = await order_factory(user=buyer)
    deal = Deal(
        id=uuid.uuid4(), order_id=order.id, buyer_id=buyer.id,
        seller_id=pending.seller.user_id, product_name="Клавиатура",
        amount_nano=1_000_000_000, commission_nano=20_000_000,
        status=DealStatus.DISPUTED, dispute_reason="не работает",
    )
    db.add(deal)
    await db.flush()

    with patch.object(admin_p2p.deal_chat_service, "push_message", AsyncMock()):
        await admin_p2p.moderator_message(
            deal.id, admin_p2p.ModeratorMessage(text="Здравствуйте, разбираемся"),
            admin=moderator, db=db,
        )

    entry = [e for e in await _audit(db) if e.action == "deal.message"][-1]
    assert entry.actor_role == "moderator"
    assert entry.details["text"] == "Здравствуйте, разбираемся"


async def test_audit_log_endpoint_filters_by_role_and_prefix(db, admin, pending):
    moderator = await _moderator_user(db, admin)
    with patch.object(telegram_service, "send_message", AsyncMock()):
        await admin_p2p.moderate_listing(
            pending.id, admin_p2p.ModerationDecision(approve=True), admin=moderator, db=db,
        )

    everything = await admin_staff.audit_log(
        actor_id=None, role=None, action=None, skip=0, limit=50, admin=admin, db=db,
    )
    mine = await admin_staff.audit_log(
        actor_id=moderator.id, role="moderator", action="listing", skip=0, limit=50,
        admin=admin, db=db,
    )

    assert everything["total"] >= 2        # создание модератора + одобрение
    assert [i["action"] for i in mine["items"]] == ["listing.approve"]
    assert mine["items"][0]["actor_role"] == "moderator"


async def test_login_log_endpoint_filters_failures(db, admin):
    await _login(db, ENV_USER, ENV_PASSWORD)
    with pytest.raises(HTTPException):
        await _login(db, ENV_USER, "wrong-password-xx")

    failures = await admin_staff.login_log(success=False, skip=0, limit=50, admin=admin, db=db)

    assert failures["total"] == 1
    assert failures["items"][0]["reason"] == "bad_password"


async def test_settings_change_is_journaled(db, admin):
    from routes import admin_finance
    await admin_finance.update_setting(
        "p2p_auto_publish_verified", admin_finance.SettingUpdate(value=True),
        admin=admin, db=db,
    )
    entry = [e for e in await _audit(db) if e.action == "settings.update"][-1]
    assert entry.target_id == "p2p_auto_publish_verified"


# ---------------------------------------------------------------------------
# Удаление фото и аватарок
# ---------------------------------------------------------------------------

@pytest.fixture
def uploads(tmp_path, monkeypatch):
    """Каталог загрузок во временной папке, с файлами и копиями."""
    monkeypatch.setattr(admin_p2p.app_settings, "UPLOAD_DIR", str(tmp_path))
    for rel in ("listings/a.png", "listings/b.png", "stores/logo.png",
                "products/placeholder.png"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 200)
    for rel in ("listings/a.png", "stores/logo.png"):
        for variant in ("_web", "_thumb"):
            copy = tmp_path / variant / "uploads" / f"{rel}.jpg"
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(b"y" * 50)
    return tmp_path


async def test_moderator_deletes_listing_photo_everywhere(db, admin, pending, uploads, category):
    moderator = await _moderator_user(db, admin)
    product = Product(
        id=uuid.uuid4(), name_ru="Клавиатура", name_en="Keyboard", description_ru="d",
        description_en="d", price_usdt=Decimal("50"), image_url="/uploads/listings/a.png",
        images=["/uploads/listings/a.png", "/uploads/listings/b.png"],
        category_id=category.id, type="p2p", owner_user_id=pending.seller.user_id,
        is_p2p=True, content_data={},
    )
    db.add(product)
    await db.flush()
    pending.product_id = product.id
    first = pending.images[0]

    with patch.object(telegram_service, "send_message", AsyncMock()) as sent:
        result = await admin_p2p.delete_listing_photo(pending.id, first.id, admin=moderator, db=db)

    assert result == {"deleted": True, "remaining": 1}
    # Из карточки товара: обложка стала следующей фотографией
    await db.refresh(product)
    assert product.images == ["/uploads/listings/b.png"]
    assert product.image_url == "/uploads/listings/b.png"
    # С диска — вместе с облегчёнными копиями
    assert not (uploads / "listings/a.png").exists()
    assert not (uploads / "_web/uploads/listings/a.png.jpg").exists()
    assert not (uploads / "_thumb/uploads/listings/a.png.jpg").exists()
    assert (uploads / "listings/b.png").exists()
    # Продавцу сказали
    assert "удалил фото" in sent.await_args.args[1]
    entry = [e for e in await _audit(db) if e.action == "photo.delete"][-1]
    assert entry.details["kind"] == "listing_image" and entry.actor_role == "moderator"


async def test_deleting_the_last_photo_falls_back_to_placeholder(db, admin, pending, uploads, category):
    moderator = await _moderator_user(db, admin)
    product = Product(
        id=uuid.uuid4(), name_ru="К", name_en="K", description_ru="d", description_en="d",
        price_usdt=Decimal("50"), image_url="/uploads/listings/a.png",
        images=["/uploads/listings/a.png"], category_id=category.id, type="p2p",
        owner_user_id=pending.seller.user_id, is_p2p=True, content_data={},
    )
    db.add(product)
    await db.flush()
    pending.product_id = product.id
    only, other = pending.images
    await db.delete(other)
    await db.flush()
    await db.refresh(pending, ["images"])

    with patch.object(telegram_service, "send_message", AsyncMock()):
        await admin_p2p.delete_listing_photo(pending.id, only.id, admin=moderator, db=db)

    await db.refresh(product)
    assert product.image_url == "/uploads/products/placeholder.png"
    assert product.images == []


async def test_shared_file_is_kept_when_another_listing_uses_it(db, admin, pending, uploads, user_factory):
    moderator = await _moderator_user(db, admin)
    other_listing = ProductListing(
        id=uuid.uuid4(), seller_id=pending.seller_id, name="Копия", description="Описание копии",
        price_usd=Decimal("1"), status=ListingStatus.DRAFT,
    )
    db.add(other_listing)
    await db.flush()
    db.add(ListingImage(
        id=uuid.uuid4(), listing_id=other_listing.id, url="/uploads/listings/a.png",
    ))
    await db.flush()

    with patch.object(telegram_service, "send_message", AsyncMock()):
        await admin_p2p.delete_listing_photo(
            pending.id, pending.images[0].id, admin=moderator, db=db,
        )

    assert (uploads / "listings/a.png").exists()


async def test_unknown_photo_is_not_found(db, admin, pending, uploads):
    moderator = await _moderator_user(db, admin)
    with pytest.raises(HTTPException) as exc:
        await admin_p2p.delete_listing_photo(pending.id, uuid.uuid4(), admin=moderator, db=db)
    assert exc.value.status_code == 404


async def test_moderator_removes_store_avatar(db, admin, pending, uploads):
    moderator = await _moderator_user(db, admin)

    with patch.object(telegram_service, "send_message", AsyncMock()):
        result = await admin_p2p.delete_seller_avatar(pending.seller_id, admin=moderator, db=db)

    assert result == {"deleted": True}
    profile = await db.get(SellerProfile, pending.seller_id)
    assert profile.avatar_url is None
    assert not (uploads / "stores/logo.png").exists()
    assert not (uploads / "_thumb/uploads/stores/logo.png.jpg").exists()
    entry = [e for e in await _audit(db) if e.action == "photo.delete"][-1]
    assert entry.details["kind"] == "store_avatar"


async def test_platform_store_logo_is_not_removable_here(db, admin):
    moderator = await _moderator_user(db, admin)
    platform = SellerProfile(
        id=uuid.uuid4(), user_id=None, display_name="Маркет", payout_wallet="",
        is_platform=True, avatar_url="/uploads/stores/p.png",
    )
    db.add(platform)
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await admin_p2p.delete_seller_avatar(platform.id, admin=moderator, db=db)
    assert exc.value.status_code == 400


async def test_file_removal_is_confined_to_the_uploads_directory(tmp_path):
    inside = tmp_path / "listings" / "x.png"
    inside.parent.mkdir()
    inside.write_bytes(b"1")
    outside = tmp_path.parent / "secret.txt"
    outside.write_bytes(b"secret")
    root = tmp_path

    assert image_variants.remove(root, "/uploads/../secret.txt") is False
    assert image_variants.remove(root, "https://evil.example/uploads/x.png") is False
    assert image_variants.remove(root, "/etc/passwd") is False
    assert outside.exists()
    # Заглушку, на которую ссылаются все товары без фото, не удаляем никогда
    placeholder = root / "products" / "placeholder.png"
    placeholder.parent.mkdir()
    placeholder.write_bytes(b"p")
    assert image_variants.remove(root, "/uploads/products/placeholder.png") is False
    assert placeholder.exists()
    # Адрес с ?v=… (аватар канала) — тот же файл
    assert image_variants.remove(root, "/uploads/listings/x.png?v=123") is True
    assert not inside.exists()
    # Повторное удаление — не ошибка
    assert image_variants.remove(root, "/uploads/listings/x.png") is False
