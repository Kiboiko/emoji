"""
Модерация заявок кнопкой в Telegram.

Права здесь проверяет бэкенд, а не бот: общий секрет INTERNAL_API_TOKEN
подтверждает только то, что запрос пришёл от нашего бота. Кто именно нажал
кнопку, секрет не говорит, а уведомления уходят в админский чат — он может
быть групповым, и кнопку там видит любой участник.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from models.category import Category
from models.p2p import ListingImage, ListingStatus, ProductListing, SellerProfile
from models.product import Product
from routes import internal

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pending_listing(db, user_factory):
    category = Category(id=uuid.uuid4(), name_ru="Вещи", name_en="User items")
    db.add(category)

    seller_user = await user_factory(username="bot_mod_seller")
    profile = SellerProfile(
        id=uuid.uuid4(), user_id=seller_user.id,
        display_name="Продавец", payout_wallet="UQWallet1234567890",
    )
    db.add(profile)
    await db.flush()

    listing = ProductListing(
        id=uuid.uuid4(), seller_id=profile.id, category_id=category.id,
        name="Клавиатура", description="Механическая, почти новая",
        price_usd=Decimal("50.00"), status=ListingStatus.PENDING,
    )
    db.add(listing)
    await db.flush()
    db.add(ListingImage(
        id=uuid.uuid4(), listing_id=listing.id, url="/uploads/listings/a.jpg", sort_order=0,
    ))
    await db.flush()
    return listing


async def _moderate(db, telegram_id: int, listing_id, approve: bool = True):
    # Уведомление продавцу шлётся реальным HTTP-запросом в Telegram —
    # в тестах его подменяем
    with patch("services.telegram_service.telegram_service.send_message", new=AsyncMock()):
        return await internal.moderate_listing_from_bot(
            internal.ModerationIn(
                telegram_user_id=telegram_id,
                listing_id=listing_id,
                approve=approve,
            ),
            db=db,
        )


async def test_admin_can_approve(db, user_factory, pending_listing):
    admin = await user_factory(username="bot_admin", is_admin=True)

    result = await _moderate(db, admin.telegram_id, pending_listing.id)

    assert result["status"] == "approved"
    await db.refresh(pending_listing)
    assert pending_listing.status == ListingStatus.APPROVED

    product = await db.get(Product, pending_listing.product_id)
    assert product is not None
    assert product.is_p2p is True
    # Сток ровно 1 — вещь одна (см. подробнее test_seller_cabinet)
    assert product.stock == 1


async def test_non_admin_is_refused(db, user_factory, pending_listing):
    """
    Кнопку нажал обычный участник админского чата.

    Ключевая проверка: без неё любой, кто видит сообщение в групповом чате,
    публиковал бы товары в каталог.
    """
    stranger = await user_factory(username="not_an_admin")

    result = await _moderate(db, stranger.telegram_id, pending_listing.id)

    assert result["reply"] == "Недостаточно прав"
    await db.refresh(pending_listing)
    assert pending_listing.status == ListingStatus.PENDING


async def test_unknown_user_is_refused(db, pending_listing):
    result = await _moderate(db, 999_999_999, pending_listing.id)

    assert result["reply"] == "Недостаточно прав"
    await db.refresh(pending_listing)
    assert pending_listing.status == ListingStatus.PENDING


async def test_reject_sends_to_admin_panel(db, user_factory, pending_listing):
    """
    Отказ кнопкой не выполняется: причину в callback не введёшь.

    Отказ без причины продавец не может исправить, и он же двигает счётчик
    отказов подряд к автоматическому ограничению.
    """
    admin = await user_factory(username="bot_admin_2", is_admin=True)

    result = await _moderate(db, admin.telegram_id, pending_listing.id, approve=False)

    assert "админку" in result["reply"]
    # Флаг, а не разбор текста reply: бот решает по нему, слать ли сообщение
    # со ссылкой на модерацию. Текст reply может измениться независимо.
    assert result["open_admin"] is True
    await db.refresh(pending_listing)
    assert pending_listing.status == ListingStatus.PENDING


async def test_second_press_is_reported(db, user_factory, pending_listing):
    """Двое администраторов нажали одну кнопку — второй получает внятный ответ."""
    admin = await user_factory(username="bot_admin_3", is_admin=True)

    await _moderate(db, admin.telegram_id, pending_listing.id)
    second = await _moderate(db, admin.telegram_id, pending_listing.id)

    assert "уже обработана" in second["reply"]
    # Второй товар в каталоге создаться не должен
    products = (await db.execute(
        select(Product).where(Product.name_ru == "Клавиатура")
    )).scalars().all()
    assert len(products) == 1


async def test_missing_listing(db, user_factory):
    admin = await user_factory(username="bot_admin_4", is_admin=True)

    result = await _moderate(db, admin.telegram_id, uuid.uuid4())

    assert result["reply"] == "Заявка не найдена"


async def test_approval_carries_every_photo_and_quantity(db, user_factory, pending_listing):
    """
    В товар уходят все фотографии заявки и заявленное количество.

    Раньше доезжала только первая картинка — остальные оставались в
    listing_images и покупателю не показывались никогда, — а сток жёстко
    равнялся единице: продавец с пятью одинаковыми ключами продавал один.
    """
    db.add(ListingImage(
        id=uuid.uuid4(), listing_id=pending_listing.id,
        url="/uploads/listings/b.jpg", sort_order=1,
    ))
    pending_listing.quantity = 5
    await db.flush()

    admin = await user_factory(username="bot_admin_gallery", is_admin=True)
    await _moderate(db, admin.telegram_id, pending_listing.id)

    product = await db.get(Product, pending_listing.product_id)
    assert product.images == ["/uploads/listings/a.jpg", "/uploads/listings/b.jpg"]
    # Первая фотография остаётся главной: на неё смотрят карточки каталога,
    # корзина и снимок заказа
    assert product.image_url == "/uploads/listings/a.jpg"
    assert product.stock == 5
    assert product.max_quantity == 5
