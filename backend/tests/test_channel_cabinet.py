"""
Кабинет автора канала: что попадает в каталог и что автор может править.

Главное, что здесь закрывается, — дыра, из-за которой подписка продавалась
до модерации. Товар под тариф заводится в момент создания тарифа, то есть
когда канал ещё лежит в черновике, и до появления Product.is_active ничто не
мешало купить доступ в неопубликованный канал.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from models.product import Product
from models.subscription import (
    Channel, ChannelStatus, Subscription, SubscriptionPlan, SubscriptionStatus,
)
from routes import admin_subscriptions, subscriptions
from services import subscription_service as subs

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def author(db, user_factory):
    return await user_factory(username="channel_author")


@pytest.fixture
async def admin_user(db, user_factory):
    return await user_factory(username="channel_moderator", is_admin=True)


@pytest.fixture
async def channel_factory(db, author):
    async def make(status: ChannelStatus = ChannelStatus.DRAFT) -> Channel:
        channel = Channel(
            id=uuid.uuid4(),
            owner_user_id=author.id,
            telegram_chat_id=-1000000000000 - uuid.uuid4().int % 100000,
            title="Закрытый канал",
            description="Исходное описание",
            status=status,
            bot_is_admin=True,
            payout_wallet="EQAuthorWallet0000",
        )
        db.add(channel)
        await db.flush()
        return channel
    return make


async def _add_plan(db, channel: Channel, author) -> SubscriptionPlan:
    """Заводит тариф через саму ручку — вместе с товаром-витриной."""
    result = await subscriptions.create_plan(
        channel.id,
        subscriptions.PlanCreate(
            title_ru="Месяц", title_en="Month",
            duration_days=30, price_usd=Decimal("5.00"),
        ),
        user=author, db=db,
    )
    plan = await db.get(SubscriptionPlan, uuid.UUID(result["id"]))
    return plan


# ---------------------------------------------------------------------------
# Дыра в модерации
# ---------------------------------------------------------------------------

async def test_plan_of_unmoderated_channel_is_not_on_sale(db, channel_factory, author):
    """Товар заводится сразу, но продаваться до одобрения не должен."""
    channel = await channel_factory(ChannelStatus.DRAFT)
    plan = await _add_plan(db, channel, author)

    product = await db.get(Product, plan.product_id)
    assert product is not None, "товар под тариф должен существовать"
    assert product.is_active is False, "подписка неопубликованного канала попала в каталог"


async def test_plan_of_active_channel_is_on_sale(db, channel_factory, author):
    channel = await channel_factory(ChannelStatus.ACTIVE)
    plan = await _add_plan(db, channel, author)

    product = await db.get(Product, plan.product_id)
    assert product.is_active is True


async def test_approval_puts_plans_on_sale(db, channel_factory, author, admin_user):
    """Решение модератора и открывает продажу — ничто другое."""
    channel = await channel_factory(ChannelStatus.PENDING)
    plan = await _add_plan(db, channel, author)
    assert (await db.get(Product, plan.product_id)).is_active is False

    # Перед одобрением права бота проверяются заново — настоящий вызов
    # Telegram в тестах недоступен
    with patch.object(
        admin_subscriptions.subscription_service,
        "verify_channel", AsyncMock(return_value=(True, None)),
    ):
        await admin_subscriptions.moderate_channel(
            channel.id,
            admin_subscriptions.ModerationDecision(approve=True),
            admin=admin_user, db=db,
        )

    await db.refresh(channel)
    assert channel.status == ChannelStatus.ACTIVE
    assert (await db.get(Product, plan.product_id)).is_active is True


async def test_suspension_takes_plans_off_sale(db, channel_factory, author, admin_user):
    channel = await channel_factory(ChannelStatus.ACTIVE)
    plan = await _add_plan(db, channel, author)
    assert (await db.get(Product, plan.product_id)).is_active is True

    await admin_subscriptions.suspend_channel(channel.id, admin=admin_user, db=db)

    assert (await db.get(Product, plan.product_id)).is_active is False


async def test_rejection_keeps_plans_off_sale(db, channel_factory, author, admin_user):
    channel = await channel_factory(ChannelStatus.PENDING)
    plan = await _add_plan(db, channel, author)

    await admin_subscriptions.moderate_channel(
        channel.id,
        admin_subscriptions.ModerationDecision(approve=False, comment="не то"),
        admin=admin_user, db=db,
    )

    await db.refresh(channel)
    assert channel.status == ChannelStatus.REJECTED
    assert (await db.get(Product, plan.product_id)).is_active is False


# ---------------------------------------------------------------------------
# Правка
# ---------------------------------------------------------------------------

async def test_author_unpublishes_channel(db, channel_factory, author):
    """Снятие с продажи по воле автора убирает тарифы из каталога."""
    channel = await channel_factory(ChannelStatus.ACTIVE)
    plan = await _add_plan(db, channel, author)

    await subscriptions.unpublish_channel(channel.id, user=author, db=db)

    await db.refresh(channel)
    assert channel.status == ChannelStatus.DRAFT
    assert (await db.get(Product, plan.product_id)).is_active is False


async def test_description_edit_returns_channel_to_moderation(db, channel_factory, author):
    """
    Описание — публичный текст, и оно же предмет модерации. Правка у
    опубликованного канала снимает его с витрины до повторной проверки,
    иначе можно подать безобидный текст и подменить после одобрения.
    """
    channel = await channel_factory(ChannelStatus.ACTIVE)
    plan = await _add_plan(db, channel, author)

    await subscriptions.update_channel(
        channel.id,
        subscriptions.ChannelUpdate(description="Совсем другое описание"),
        user=author, db=db,
    )

    await db.refresh(channel)
    assert channel.status == ChannelStatus.DRAFT
    assert (await db.get(Product, plan.product_id)).is_active is False


async def test_wallet_edit_keeps_channel_published(db, channel_factory, author):
    """Кошелёк покупателя не касается — снимать канал с продажи незачем."""
    channel = await channel_factory(ChannelStatus.ACTIVE)
    plan = await _add_plan(db, channel, author)

    await subscriptions.update_channel(
        channel.id,
        subscriptions.ChannelUpdate(payout_wallet="EQNewWallet000000000"),
        user=author, db=db,
    )

    await db.refresh(channel)
    assert channel.status == ChannelStatus.ACTIVE
    assert channel.payout_wallet == "EQNewWallet000000000"
    assert (await db.get(Product, plan.product_id)).is_active is True


async def test_plan_price_edit_reaches_the_catalog(db, channel_factory, author):
    channel = await channel_factory(ChannelStatus.ACTIVE)
    plan = await _add_plan(db, channel, author)

    await subscriptions.update_plan(
        channel.id, plan.id,
        subscriptions.PlanUpdate(price_usd=Decimal("9.99"), title_ru="Полгода"),
        user=author, db=db,
    )

    product = await db.get(Product, plan.product_id)
    assert product.price_usdt == Decimal("9.99")
    assert "Полгода" in product.name_ru


async def test_disabled_plan_leaves_the_catalog(db, channel_factory, author):
    """Отключённый тариф виден автору, но не продаётся."""
    channel = await channel_factory(ChannelStatus.ACTIVE)
    plan = await _add_plan(db, channel, author)

    await subscriptions.update_plan(
        channel.id, plan.id, subscriptions.PlanUpdate(is_active=False),
        user=author, db=db,
    )

    assert (await db.get(Product, plan.product_id)).is_active is False


# ---------------------------------------------------------------------------
# Удаление
# ---------------------------------------------------------------------------

async def test_unsold_plan_is_deleted_with_its_product(db, channel_factory, author):
    channel = await channel_factory(ChannelStatus.DRAFT)
    plan = await _add_plan(db, channel, author)
    product_id = plan.product_id

    await subscriptions.delete_plan(channel.id, plan.id, user=author, db=db)

    assert await db.get(SubscriptionPlan, plan.id) is None
    assert await db.get(Product, product_id) is None


async def test_sold_plan_cannot_be_deleted(db, channel_factory, author, user_factory):
    """История оплат важнее удобства: проданный тариф только отключается."""
    channel = await channel_factory(ChannelStatus.ACTIVE)
    plan = await _add_plan(db, channel, author)

    buyer = await user_factory(username="sub_buyer")
    db.add(Subscription(
        id=uuid.uuid4(), user_id=buyer.id, channel_id=channel.id,
        plan_id=plan.id, status=SubscriptionStatus.ACTIVE,
    ))
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await subscriptions.delete_plan(channel.id, plan.id, user=author, db=db)
    assert exc.value.status_code == 400

    assert await db.get(SubscriptionPlan, plan.id) is not None


async def test_channel_with_subscriptions_cannot_be_deleted(
    db, channel_factory, author, user_factory,
):
    """
    Subscription висит на канале с ondelete=CASCADE — удаление канала стёрло
    бы историю оплат вместе с журналом выдачи доступа.
    """
    channel = await channel_factory(ChannelStatus.ACTIVE)
    await _add_plan(db, channel, author)

    buyer = await user_factory(username="sub_buyer2")
    db.add(Subscription(
        id=uuid.uuid4(), user_id=buyer.id, channel_id=channel.id,
        status=SubscriptionStatus.EXPIRED,
    ))
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await subscriptions.delete_channel(channel.id, user=author, db=db)
    assert exc.value.status_code == 400

    assert await db.get(Channel, channel.id) is not None


async def test_empty_channel_is_deleted(db, channel_factory, author):
    channel = await channel_factory(ChannelStatus.DRAFT)
    await _add_plan(db, channel, author)

    await subscriptions.delete_channel(channel.id, user=author, db=db)

    assert await db.get(Channel, channel.id) is None


async def test_stranger_cannot_touch_someone_elses_channel(db, channel_factory, user_factory):
    channel = await channel_factory(ChannelStatus.ACTIVE)
    stranger = await user_factory(username="stranger_author")

    with pytest.raises(HTTPException) as exc:
        await subscriptions.update_channel(
            channel.id, subscriptions.ChannelUpdate(description="Захват"),
            user=stranger, db=db,
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Каталог
# ---------------------------------------------------------------------------

async def test_catalog_hides_inactive_products(db, channel_factory, author):
    """Сквозная проверка: то, что погашено, каталог не отдаёт."""
    from routes import products as products_routes

    channel = await channel_factory(ChannelStatus.DRAFT)
    plan = await _add_plan(db, channel, author)

    listed = await products_routes.get_products(db=db)
    assert plan.product_id not in {p.id for p in listed}

    channel.status = ChannelStatus.ACTIVE
    await subs.sync_plan_products(db, channel)
    await db.flush()

    listed = await products_routes.get_products(db=db)
    assert plan.product_id in {p.id for p in listed}


async def test_catalog_shows_channel_as_author(db, channel_factory, author):
    """
    Подписка должна приходить в витрину с именем канала: до этого покупатель
    не видел, в чей канал он платит.
    """
    from routes import products as products_routes

    channel = await channel_factory(ChannelStatus.ACTIVE)
    channel.is_verified = True
    plan = await _add_plan(db, channel, author)

    listed = await products_routes.get_products(db=db)
    item = next(p for p in listed if p.id == plan.product_id)

    assert item.author_kind == "channel"
    assert item.author_name == channel.title
    assert item.author_verified is True
