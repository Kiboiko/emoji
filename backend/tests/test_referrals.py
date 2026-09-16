"""
Реферальная программа: настраиваемые проценты, два уровня, типы покупок.

Деньги здесь начисляются автоматически при каждой оплате, и ошибка тихо
раздаёт средства платформы. Поэтому проверяется не только «начислилось», но и
«не начислилось дважды» и «не начислилось там, где выключено».
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from models.order import OrderItem
from models.referral import ReferralTransaction
from services import finance_service as fin
from services import referral_service as refs
from services import settings_service

pytestmark = pytest.mark.asyncio

USD = "USD"


@pytest.fixture
async def chain(db, user_factory):
    """Цепочка: grandparent -> parent -> buyer."""
    grandparent = await user_factory(username="ref_grandparent")
    parent = await user_factory(username="ref_parent", referrer_id=grandparent.id)
    buyer = await user_factory(username="ref_buyer", referrer_id=parent.id)
    await db.flush()
    return grandparent, parent, buyer


@pytest.fixture
async def order_with_items(db, order_factory):
    """
    Заказ с позициями заданных типов.

    Реферальные считаются по позициям, поэтому заказ без них бесполезен:
    именно снимки позиций решают, с чего начислять.
    """
    async def make(user, items: list[tuple[str, str]]):
        """items: список (тип, цена). Тип — product | subscription | p2p."""
        total = sum(Decimal(price) for _, price in items)
        order = await order_factory(user, total_usdt=str(total))

        for kind, price in items:
            snapshot = {"name_ru": "Товар", "type": "digital", "is_p2p": False}
            if kind == "subscription":
                snapshot["type"] = "subscription"
            elif kind == "p2p":
                snapshot["is_p2p"] = True

            db.add(OrderItem(
                id=uuid.uuid4(), order_id=order.id, product_id=None,
                product_snapshot=snapshot, quantity=1, price_usdt=Decimal(price),
            ))

        await db.flush()
        return order

    return make


async def _balance_cents(db, user) -> int:
    account = (await db.execute(
        select(fin.Account).where(
            fin.Account.owner_type == fin.AccountOwnerType.USER,
            fin.Account.owner_id == user.id,
            fin.Account.currency == USD,
        )
    )).scalars().first()
    return account.balance_minor if account else 0


# ---------------------------------------------------------------------------
# Первый уровень
# ---------------------------------------------------------------------------

async def test_l1_accrual_uses_setting(db, chain, order_with_items):
    """Процент берётся из настройки, а не из зашитого значения."""
    _, parent, buyer = chain
    await settings_service.set_setting(db, "referral_l1_bp", 500)   # 5%
    order = await order_with_items(buyer, [("product", "100.00")])

    await refs.process_referral_commission(db, order, buyer)

    assert await _balance_cents(db, parent) == 500   # 5% от 10000 центов


async def test_changed_percent_applies_to_next_order(db, chain, order_with_items):
    """
    Изменение процента действует со следующей покупки и без рестарта.

    Это прямой критерий приёмки этапа: заказчик правит процент в админке и
    ожидает, что он сработает сразу.
    """
    _, parent, buyer = chain

    await settings_service.set_setting(db, "referral_l1_bp", 300)
    first = await order_with_items(buyer, [("product", "100.00")])
    await refs.process_referral_commission(db, first, buyer)
    assert await _balance_cents(db, parent) == 300

    await settings_service.set_setting(db, "referral_l1_bp", 1000)
    second = await order_with_items(buyer, [("product", "100.00")])
    await refs.process_referral_commission(db, second, buyer)

    assert await _balance_cents(db, parent) == 300 + 1000


async def test_accrual_is_idempotent(db, chain, order_with_items):
    """Повторный вызов по тому же заказу не должен удваивать выплату."""
    _, parent, buyer = chain
    await settings_service.set_setting(db, "referral_l1_bp", 300)
    order = await order_with_items(buyer, [("product", "100.00")])

    await refs.process_referral_commission(db, order, buyer)
    await refs.process_referral_commission(db, order, buyer)

    assert await _balance_cents(db, parent) == 300
    rows = (await db.execute(
        select(ReferralTransaction).where(ReferralTransaction.order_id == order.id)
    )).scalars().all()
    assert len(rows) == 1


async def test_user_without_referrer_gets_nothing(db, user_factory, order_with_items):
    loner = await user_factory(username="ref_loner")
    order = await order_with_items(loner, [("product", "100.00")])

    await refs.process_referral_commission(db, order, loner)

    rows = (await db.execute(select(ReferralTransaction))).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# Второй уровень
# ---------------------------------------------------------------------------

async def test_l2_disabled_by_default(db, chain, order_with_items):
    """Нулевой referral_l2_bp полностью выключает второй уровень."""
    grandparent, _, buyer = chain
    await settings_service.set_setting(db, "referral_l1_bp", 300)
    await settings_service.set_setting(db, "referral_l2_bp", 0)
    order = await order_with_items(buyer, [("product", "100.00")])

    await refs.process_referral_commission(db, order, buyer)

    assert await _balance_cents(db, grandparent) == 0


async def test_l2_accrual(db, chain, order_with_items):
    grandparent, parent, buyer = chain
    await settings_service.set_setting(db, "referral_l1_bp", 300)
    await settings_service.set_setting(db, "referral_l2_bp", 100)
    order = await order_with_items(buyer, [("product", "100.00")])

    await refs.process_referral_commission(db, order, buyer)

    assert await _balance_cents(db, parent) == 300
    assert await _balance_cents(db, grandparent) == 100

    rows = (await db.execute(
        select(ReferralTransaction)
        .where(ReferralTransaction.order_id == order.id)
        .order_by(ReferralTransaction.level)
    )).scalars().all()
    assert [r.level for r in rows] == [1, 2]
    assert [r.percent_bp_applied for r in rows] == [300, 100]
    assert all(r.source == "product" for r in rows)
    assert [r.amount_minor for r in rows] == [300, 100]


async def test_l2_skipped_on_cycle(db, user_factory, order_with_items):
    """
    Замкнутая цепочка не должна приносить два начисления одному человеку.

    A пригласил B, а B по ошибке записан реферером A. Без проверки A получил бы
    и первый уровень, и второй с одной покупки.
    """
    a = await user_factory(username="cycle_a")
    b = await user_factory(username="cycle_b", referrer_id=a.id)
    a.referrer_id = b.id
    await db.flush()

    await settings_service.set_setting(db, "referral_l1_bp", 300)
    await settings_service.set_setting(db, "referral_l2_bp", 100)
    order = await order_with_items(b, [("product", "100.00")])

    await refs.process_referral_commission(db, order, b)

    # A получает только первый уровень; второй ведёт на самого покупателя
    assert await _balance_cents(db, a) == 300
    assert await _balance_cents(db, b) == 0


# ---------------------------------------------------------------------------
# Типы покупок
# ---------------------------------------------------------------------------

async def test_disabled_source_gets_no_commission(db, chain, order_with_items):
    """Выключенный тип покупки не приносит реферальных."""
    _, parent, buyer = chain
    await settings_service.set_setting(db, "referral_l1_bp", 300)
    await settings_service.set_setting(db, "referral_applies_to", ["product"])
    order = await order_with_items(buyer, [("subscription", "100.00")])

    await refs.process_referral_commission(db, order, buyer)

    assert await _balance_cents(db, parent) == 0


async def test_mixed_order_counts_only_enabled_part(db, chain, order_with_items):
    """
    В смешанном заказе начисление идёт только с разрешённой части.

    Раньше комиссия считалась от order.total_usdt целиком, поэтому выключение
    типа не влияло ни на что, пока в заказе был хоть один обычный товар.
    """
    _, parent, buyer = chain
    await settings_service.set_setting(db, "referral_l1_bp", 1000)   # 10%
    await settings_service.set_setting(db, "referral_applies_to", ["product"])
    order = await order_with_items(
        buyer, [("product", "50.00"), ("subscription", "100.00"), ("p2p", "30.00")],
    )

    await refs.process_referral_commission(db, order, buyer)

    # 10% только с 50 долларов, а не со 180
    assert await _balance_cents(db, parent) == 500


async def test_p2p_source_recorded(db, chain, order_with_items):
    _, parent, buyer = chain
    await settings_service.set_setting(db, "referral_l1_bp", 300)
    await settings_service.set_setting(db, "referral_applies_to", ["p2p"])
    order = await order_with_items(buyer, [("p2p", "100.00")])

    await refs.process_referral_commission(db, order, buyer)

    row = (await db.execute(
        select(ReferralTransaction).where(ReferralTransaction.order_id == order.id)
    )).scalars().one()
    assert row.source == "p2p"


async def test_item_source_classification():
    assert refs.item_source({"is_p2p": True, "type": "digital"}) == "p2p"
    assert refs.item_source({"type": "subscription"}) == "subscription"
    assert refs.item_source({"type": "digital"}) == "product"
    assert refs.item_source({}) == "product"


async def test_quantity_is_counted(db, chain, order_factory):
    """Комиссия считается с цены, умноженной на количество."""
    _, parent, buyer = chain
    await settings_service.set_setting(db, "referral_l1_bp", 1000)

    order = await order_factory(buyer, total_usdt="60.00")
    db.add(OrderItem(
        id=uuid.uuid4(), order_id=order.id, product_id=None,
        product_snapshot={"type": "digital", "is_p2p": False},
        quantity=3, price_usdt=Decimal("20.00"),
    ))
    await db.flush()

    await refs.process_referral_commission(db, order, buyer)

    assert await _balance_cents(db, parent) == 600    # 10% от 60 долларов


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------

async def _history(db, admin, **overrides):
    """
    Вызов админского эндпоинта с явными значениями фильтров.

    Роут вызывается напрямую, без HTTP, поэтому значения по умолчанию остаются
    объектами Query и до SQL их доводить нельзя — подставляем сами.
    """
    from routes import admin_referrals

    params = dict(
        level=None, source=None, date_from=None, date_to=None,
        referrer_id=None, search=None, skip=0, limit=50,
    )
    params.update(overrides)
    return await admin_referrals.list_accruals(_=admin, db=db, **params)


async def test_admin_history_filters_by_level(db, chain, order_with_items, user_factory):
    grandparent, parent, buyer = chain
    admin = await user_factory(username="ref_admin", is_admin=True)
    await settings_service.set_setting(db, "referral_l1_bp", 300)
    await settings_service.set_setting(db, "referral_l2_bp", 100)
    order = await order_with_items(buyer, [("product", "100.00")])
    await refs.process_referral_commission(db, order, buyer)

    everything = await _history(db, admin)
    assert everything["total"] == 2

    only_l2 = await _history(db, admin, level=2)
    assert only_l2["total"] == 1
    assert only_l2["items"][0]["referrer"]["id"] == str(grandparent.id)
    assert only_l2["items"][0]["amount"] == "1.00"

    # Имена подтягиваются, а не остаются голыми идентификаторами
    assert only_l2["items"][0]["referral"]["username"] == "ref_buyer"


async def test_admin_history_filters_by_source(db, chain, order_with_items, user_factory):
    _, _, buyer = chain
    admin = await user_factory(username="ref_admin_2", is_admin=True)
    await settings_service.set_setting(db, "referral_l1_bp", 300)
    await settings_service.set_setting(db, "referral_applies_to", ["p2p"])
    order = await order_with_items(buyer, [("p2p", "100.00")])
    await refs.process_referral_commission(db, order, buyer)

    assert (await _history(db, admin, source="p2p"))["total"] == 1
    assert (await _history(db, admin, source="product"))["total"] == 0


async def test_admin_top_referrers(db, chain, order_with_items, user_factory):
    from routes import admin_referrals

    _, parent, buyer = chain
    admin = await user_factory(username="ref_admin_3", is_admin=True)
    await settings_service.set_setting(db, "referral_l1_bp", 1000)

    for _ in range(2):
        order = await order_with_items(buyer, [("product", "100.00")])
        await refs.process_referral_commission(db, order, buyer)

    top = await admin_referrals.top_referrers(
        limit=20, date_from=None, date_to=None, _=admin, db=db,
    )

    assert top["items"][0]["user_id"] == str(parent.id)
    assert top["items"][0]["accruals"] == 2
    assert top["items"][0]["earned"] == "20.00"
    assert top["items"][0]["invited"] == 1


async def test_statistics_separates_levels(db, chain, order_with_items):
    """
    Второй уровень показывается отдельно.

    У начисления второго уровня referral_id — покупатель-внук, которого нет в
    списке прямых рефералов, поэтому в разбивке по людям его сумма потерялась
    бы совсем.
    """
    grandparent, parent, buyer = chain
    await settings_service.set_setting(db, "referral_l1_bp", 300)
    await settings_service.set_setting(db, "referral_l2_bp", 100)
    order = await order_with_items(buyer, [("product", "100.00")])
    await refs.process_referral_commission(db, order, buyer)

    stats = await refs.get_referral_statistics(db, grandparent)

    assert stats["level2_earnings"] == 1.0
    # Прямой реферал дедушки — это parent, который сам ничего не покупал
    assert stats["referral_count"] == 1
    assert stats["referrals"][0]["commission_earned"] == 0
