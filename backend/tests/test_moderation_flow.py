"""
Поток модерации заявок: уведомления, обязательная категория, публикация без
проверки для проверенных продавцов.

Главное, что здесь проверяется: уведомление модераторам приходит КАЖДЫЙ раз,
когда заявка попадает на проверку. Раньше оно уходило только при первой
отправке — после правки названия опубликованного товара заявка тихо ждала в
очереди, и модераторы о ней не знали.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from models.category import Category
from models.p2p import (
    ListingImage, ListingStatus, ProductListing, SellerProfile, SellerStatus,
)
from models.product import Product
from routes import admin_p2p, p2p
from services import moderation_service, settings_service
from services.telegram_service import telegram_service

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Игры", name_en="Games")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def profile(db, user_factory):
    user = await user_factory(username="flow_seller")
    row = SellerProfile(
        id=uuid.uuid4(), user_id=user.id,
        display_name="Flow Shop", payout_wallet="UQSellerWallet0000",
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def seller_account(db, profile):
    from models.user import User
    return await db.get(User, profile.user_id)


@pytest.fixture
def telegram(monkeypatch):
    """Админский чат из двух получателей и подменённая отправка."""
    monkeypatch.setattr(telegram_service, "admin_chat_ids", ["111", "222"])
    with patch.object(telegram_service, "send_message", AsyncMock()) as sent:
        yield sent


async def _listing(db, profile, category, status, with_product=False):
    listing = ProductListing(
        id=uuid.uuid4(), seller_id=profile.id,
        category_id=category.id if category else None,
        name="Клавиатура", name_en="Keyboard",
        description="Механическая, почти новая",
        description_en="Mechanical, almost new",
        price_usd=Decimal("50.00"), status=status,
    )
    db.add(listing)
    await db.flush()
    db.add(ListingImage(
        id=uuid.uuid4(), listing_id=listing.id, url="/uploads/listings/a.jpg", sort_order=0,
    ))
    if with_product:
        product = Product(
            id=uuid.uuid4(), name_ru=listing.name, name_en=listing.name_en,
            description_ru=listing.description, description_en=listing.description_en,
            price_usdt=listing.price_usd, image_url="/uploads/listings/a.jpg",
            category_id=category.id, type="p2p", min_quantity=1, max_quantity=1,
            stock=1, content_data={}, owner_user_id=profile.user_id, is_p2p=True,
        )
        db.add(product)
        await db.flush()
        listing.product_id = product.id
    await db.flush()
    await db.refresh(listing, ["images"])
    return listing


def _texts(sent) -> list[str]:
    return [call.args[1] for call in sent.await_args_list]


# ---------------------------------------------------------------------------
# Уведомления
# ---------------------------------------------------------------------------

async def test_submit_notifies_every_moderator_chat(db, profile, category, telegram, seller_account):
    listing = await _listing(db, profile, category, ListingStatus.DRAFT)

    result = await p2p.submit_listing(listing.id, user=seller_account, db=db)

    assert result == {"status": "pending", "published": False}
    assert telegram.await_count == 2
    assert all(t.startswith("Новая заявка на размещение") for t in _texts(telegram))
    # Кнопки решения — в каждом сообщении
    assert all(call.kwargs["reply_markup"] for call in telegram.await_args_list)


async def test_every_edit_of_published_listing_notifies_moderators(
    db, profile, category, telegram, seller_account,
):
    """Две правки подряд — два уведомления. Раньше не приходило ни одного."""
    listing = await _listing(db, profile, category, ListingStatus.APPROVED, with_product=True)

    first = await p2p.update_listing(
        listing.id, p2p.ListingUpdate(name="Клавиатура Keychron"),
        user=seller_account, db=db,
    )
    assert first["remoderating"] is True
    assert telegram.await_count == 2
    assert all(t.startswith("Товар изменён и снова ждёт проверки") for t in _texts(telegram))
    assert "Клавиатура Keychron" in _texts(telegram)[0]

    # Модератор одобрил, продавец правит ещё раз — снова уведомление
    await db.refresh(listing)
    listing.status = ListingStatus.APPROVED
    await db.flush()
    telegram.reset_mock()

    second = await p2p.update_listing(
        listing.id, p2p.ListingUpdate(name="Клавиатура Keychron K2"),
        user=seller_account, db=db,
    )
    assert second["remoderating"] is True
    assert telegram.await_count == 2


async def test_untouched_edit_does_not_notify(db, profile, category, telegram, seller_account):
    listing = await _listing(db, profile, category, ListingStatus.APPROVED, with_product=True)

    result = await p2p.update_listing(
        listing.id, p2p.ListingUpdate(name=listing.name), user=seller_account, db=db,
    )

    assert result["remoderating"] is False
    telegram.assert_not_called()


async def test_photo_change_of_published_listing_notifies(
    db, profile, category, telegram, seller_account,
):
    listing = await _listing(db, profile, category, ListingStatus.APPROVED, with_product=True)
    second = ListingImage(
        id=uuid.uuid4(), listing_id=listing.id, url="/uploads/listings/b.jpg", sort_order=1,
    )
    db.add(second)
    await db.flush()
    await db.refresh(listing, ["images"])

    await p2p.delete_listing_image(listing.id, second.id, user=seller_account, db=db)

    assert telegram.await_count == 2
    assert _texts(telegram)[0].startswith("Товар изменён")


async def test_notification_failure_does_not_break_submit(
    db, profile, category, seller_account, monkeypatch,
):
    monkeypatch.setattr(telegram_service, "admin_chat_ids", ["111"])
    with patch.object(
        telegram_service, "send_message", AsyncMock(side_effect=RuntimeError("telegram down")),
    ):
        listing = await _listing(db, profile, category, ListingStatus.DRAFT)
        result = await p2p.submit_listing(listing.id, user=seller_account, db=db)

    assert result["status"] == "pending"


# ---------------------------------------------------------------------------
# Категория обязательна
# ---------------------------------------------------------------------------

async def test_listing_payload_requires_category():
    with pytest.raises(ValidationError):
        p2p.ListingCreate(
            name="Клавиатура", name_en="Keyboard",
            description="Механическая, почти новая", description_en="Mechanical, almost new",
            price_usd=Decimal("10"), accept_terms=True,
        )


async def test_create_listing_with_unknown_category_is_refused(db, profile, seller_account):
    payload = p2p.ListingCreate(
        name="Клавиатура", name_en="Keyboard",
        description="Механическая, почти новая", description_en="Mechanical, almost new",
        price_usd=Decimal("10"), category_id=uuid.uuid4(), accept_terms=True,
    )
    with pytest.raises(HTTPException) as exc:
        await p2p.create_listing(payload, user=seller_account, db=db)
    assert exc.value.status_code == 400
    assert "категорию" in exc.value.detail


async def test_legacy_user_items_category_is_hidden_and_not_accepted(
    db, profile, category, seller_account,
):
    from routes import categories as categories_routes

    legacy = Category(id=uuid.uuid4(), name_ru="Товары пользователей", name_en="User items")
    db.add(legacy)
    await db.flush()

    public = await categories_routes.get_categories(lang="ru", db=db)
    assert category.id in {c.id for c in public}
    assert legacy.id not in {c.id for c in public}

    payload = p2p.ListingCreate(
        name="Клавиатура", name_en="Keyboard",
        description="Механическая, почти новая", description_en="Mechanical, almost new",
        price_usd=Decimal("10"), category_id=legacy.id, accept_terms=True,
    )
    with pytest.raises(HTTPException) as exc:
        await p2p.create_listing(payload, user=seller_account, db=db)
    assert exc.value.status_code == 400


async def test_legacy_listing_without_category_cannot_be_submitted(
    db, profile, category, telegram, seller_account,
):
    listing = await _listing(db, profile, None, ListingStatus.DRAFT)

    with pytest.raises(HTTPException) as exc:
        await p2p.submit_listing(listing.id, user=seller_account, db=db)
    assert exc.value.status_code == 400
    telegram.assert_not_called()


async def test_moderator_cannot_approve_listing_without_category(db, user_factory, profile):
    admin = await user_factory(username="flow_admin", is_admin=True)
    listing = await _listing(db, profile, None, ListingStatus.PENDING)

    with pytest.raises(HTTPException) as exc:
        await admin_p2p.moderate_listing(
            listing.id, admin_p2p.ModerationDecision(approve=True), admin=admin, db=db,
        )
    assert exc.value.status_code == 400
    # Ни товара в каталоге, ни «товара пользователей»
    assert (await db.execute(select(Product))).scalars().all() == []
    assert (await db.execute(
        select(Category).where(Category.name_en == "User items")
    )).scalars().first() is None


async def test_moderator_list_shows_english_texts_and_photo_ids(db, user_factory, profile, category):
    admin = await user_factory(username="flow_admin3", is_admin=True)
    await _listing(db, profile, category, ListingStatus.PENDING)

    page = await admin_p2p.list_listings(
        status=ListingStatus.PENDING, skip=0, limit=50, admin=admin, db=db,
    )

    item = page["items"][0]
    assert item["name_en"] == "Keyboard" and item["description_en"] == "Mechanical, almost new"
    assert [p["url"] for p in item["image_items"]] == item["images"]
    assert all(p["id"] for p in item["image_items"])


async def test_approved_product_lands_in_chosen_category(db, user_factory, profile, category):
    admin = await user_factory(username="flow_admin2", is_admin=True)
    listing = await _listing(db, profile, category, ListingStatus.PENDING)

    with patch.object(telegram_service, "send_message", AsyncMock()):
        await admin_p2p.moderate_listing(
            listing.id, admin_p2p.ModerationDecision(approve=True), admin=admin, db=db,
        )

    product = await db.get(Product, listing.product_id)
    assert product.category_id == category.id
    assert product.is_active is True


# ---------------------------------------------------------------------------
# Публикация без проверки
# ---------------------------------------------------------------------------

async def _enable_auto_publish(db):
    await settings_service.set_setting(db, "p2p_auto_publish_verified", True)


async def test_verified_seller_is_published_without_review(
    db, profile, category, telegram, seller_account,
):
    await _enable_auto_publish(db)
    profile.is_verified = True
    listing = await _listing(db, profile, category, ListingStatus.DRAFT)

    result = await p2p.submit_listing(listing.id, user=seller_account, db=db)

    assert result == {"status": "approved", "published": True}
    product = await db.get(Product, listing.product_id)
    assert product.is_active is True and product.stock == 1
    await db.refresh(listing)
    assert listing.moderation_comment == moderation_service.AUTO_PUBLISH_COMMENT
    assert listing.moderator_id is None
    # Модераторам — сообщение для сведения, без кнопок решения
    assert telegram.await_count == 2
    assert all(t.startswith("Опубликовано без проверки") for t in _texts(telegram))
    assert all(call.kwargs["reply_markup"] is None for call in telegram.await_args_list)


async def test_edit_of_verified_sellers_listing_is_republished_at_once(
    db, profile, category, telegram, seller_account,
):
    await _enable_auto_publish(db)
    profile.is_verified = True
    listing = await _listing(db, profile, category, ListingStatus.APPROVED, with_product=True)

    result = await p2p.update_listing(
        listing.id, p2p.ListingUpdate(name="Клавиатура Keychron"),
        user=seller_account, db=db,
    )

    assert result["published"] is True and result["remoderating"] is False
    product = await db.get(Product, listing.product_id)
    assert product.is_active is True
    assert product.name_ru == "Клавиатура Keychron"


async def test_option_off_means_verified_seller_still_goes_to_moderator(
    db, profile, category, telegram, seller_account,
):
    profile.is_verified = True
    listing = await _listing(db, profile, category, ListingStatus.DRAFT)

    result = await p2p.submit_listing(listing.id, user=seller_account, db=db)

    assert result["published"] is False
    await db.refresh(listing)
    assert listing.status == ListingStatus.PENDING


async def test_unverified_seller_goes_to_moderator_even_with_option_on(
    db, profile, category, telegram, seller_account,
):
    await _enable_auto_publish(db)
    listing = await _listing(db, profile, category, ListingStatus.DRAFT)

    result = await p2p.submit_listing(listing.id, user=seller_account, db=db)

    assert result["published"] is False


async def test_restricted_verified_seller_goes_to_moderator(
    db, profile, category, telegram,
):
    await _enable_auto_publish(db)
    profile.is_verified = True
    profile.status = SellerStatus.RESTRICTED

    assert await moderation_service.can_publish_without_review(db, profile) is False


async def test_verified_seller_without_category_still_needs_moderator(
    db, profile, category, telegram,
):
    """Доверие не отменяет обязательных полей."""
    await _enable_auto_publish(db)
    profile.is_verified = True
    listing = await _listing(db, profile, None, ListingStatus.PENDING)

    outcome = await moderation_service.submit_for_review(db, listing, profile, edited=False)

    assert outcome == "pending"
    await db.refresh(listing)
    assert listing.status == ListingStatus.PENDING
