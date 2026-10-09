from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, or_
from sqlalchemy.orm import selectinload
import json
import logging
import math
import uuid
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal

from database import get_db
from models.user import User
from models.order import Order, OrderStatus, OrderItem
from models.cart import CartItem
from models.product import Product
from models.digital_item import DigitalItem
from models.payment import Payment, PaymentStatus
from models.subscription import Channel, SubscriptionPlan
from schemas.order import OrderCreate, OrderResponse
from utils.auth import get_current_user, require_admin
from services import deal_chat_service, deal_service, payment_service, settings_service, stock_service, subscription_service, terms_service
from services.money import to_minor
from services.telegram_service import telegram_service
from services.referral_service import process_referral_commission
from utils.websockets import manager
from fastapi.encoders import jsonable_encoder
from schemas.product import ProductBroadcast

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["Orders"])


@router.get("", response_model=list[OrderResponse])
async def get_user_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's order history"""
    stmt = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.reviews)
    ).where(
        Order.user_id == user.id,
        Order.status.in_([OrderStatus.COMPLETED, OrderStatus.PAID])
    ).order_by(Order.created_at.desc())
    result = await db.execute(stmt)
    orders = result.scalars().all()
    
    # Manually populate is_reviewed flag
    response = []
    for order in orders:
        order_data = OrderResponse.model_validate(order)
        reviewed_product_ids = {r.product_id for r in order.reviews}
        for item in order_data.items:
            item.is_reviewed = item.product_id in reviewed_product_ids
        response.append(order_data)
        
    return response


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get order details"""
    stmt = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.reviews)
    ).where(Order.id == uuid.UUID(order_id))
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")
    
    order_data = OrderResponse.model_validate(order)
    reviewed_product_ids = {r.product_id for r in order.reviews}
    for item in order_data.items:
        item.is_reviewed = item.product_id in reviewed_product_ids
        
    return order_data


@router.get("/{order_id}/items/{item_id}/delivery")
async def item_delivery(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Что покупатель получил по позиции заказа: ключи, инструкцию, данные услуги.

    Раньше купленное уходило только файлом в Telegram, а в приложении его не
    было вовсе — потерял сообщение, и ключа больше нигде нет. Теперь его
    видно на странице покупки в «Мои сделки».

    Только владельцу и только после оплаты: снапшот пишется при оформлении
    заказа, и без проверки статуса инструкцию снова можно было бы прочитать,
    не заплатив (см. tests/test_instruction_secrecy.py).
    """
    order = await db.get(Order, order_id)
    if order is None or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if order.status not in (OrderStatus.PAID, OrderStatus.COMPLETED):
        raise HTTPException(status_code=403, detail="Заказ не оплачен")

    item = (
        await db.execute(
            select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order.id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Позиция не найдена")

    snapshot = item.product_snapshot or {}
    kind = "p2p" if snapshot.get("is_p2p") else (snapshot.get("type") or "digital")
    result: dict = {"kind": kind, "keys": [], "instruction": None, "link": None}

    if kind == "digital":
        rows = (
            await db.execute(
                select(DigitalItem.content).where(
                    DigitalItem.order_id == order.id,
                    DigitalItem.product_id == item.product_id,
                )
            )
        ).scalars().all()
        result["keys"] = [row for row in rows if row]
    elif kind == "instruction":
        result["instruction"] = (snapshot.get("content_data") or {}).get("instruction") or None
    elif kind == "service":
        # Услугу выполняет админ вручную — показываем, что передал покупатель
        result["link"] = (item.user_data or {}).get("link")
    return result


@router.post("/{order_id}/cancel", response_model=dict)
async def cancel_order(
    order_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Отмена покупателем своего неоплаченного заказа.

    Без неё брошенный checkout держал товар до срабатывания планировщика —
    до часа. Для товара пользователя это вещь в единственном экземпляре:
    чужая неудачная оплата убирала её с витрины, и ни покупатель, ни
    продавец ничего сделать не могли.

    Отменяем ТОЛЬКО ожидающий оплаты заказ и только свой. Оплаченный заказ
    отменить нельзя: деньги уже пришли, и возврат — это разбор через
    поддержку, а не кнопка.
    """
    order = (
        await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == uuid.UUID(order_id))
        )
    ).scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if order.status == OrderStatus.CANCELLED:
        # Повторное нажатие — не ошибка: кнопка могла не успеть исчезнуть
        return {"message": "Order already cancelled", "status": order.status.value}

    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="Отменить можно только заказ, ожидающий оплаты",
        )

    # Платёж мог уже подтвердиться в блокчейне, пока пользователь жал кнопку.
    # Проверяем перед отменой, иначе отменим оплаченный заказ и потеряем деньги.
    payments = (
        await db.execute(select(Payment).where(Payment.order_id == order.id))
    ).scalars().all()
    if any(p.status == PaymentStatus.CONFIRMED for p in payments):
        raise HTTPException(
            status_code=400,
            detail="Платёж уже подтверждён, заказ отменить нельзя",
        )

    released = await stock_service.release_order(db, order, expire_payments=True)

    await db.commit()
    logger.info("[ORDER] Заказ %s отменён покупателем, освобождено позиций: %s",
                order.id, len(released))
    await _broadcast_products(db, released)

    return {"message": "Order cancelled", "status": order.status.value}


async def _broadcast_products(db: AsyncSession, product_ids: list[uuid.UUID]) -> None:
    """Рассылает витринам новый остаток — вернувшийся товар появляется сразу."""
    for product_id in product_ids:
        product = await db.get(Product, product_id)
        if product is not None:
            await manager.broadcast({
                "type": "product_updated",
                "data": jsonable_encoder(ProductBroadcast.model_validate(product)),
            })


# Меньше этого времени на счёте — переиспользовать заказ бессмысленно:
# покупатель не успеет подтвердить перевод, и счёт истечёт на полпути
REUSE_MIN_LEFT = timedelta(minutes=2)


def _contents(pairs) -> Counter:
    """Состав заказа или корзины: товар, количество, цена, данные покупателя."""
    return Counter(
        (
            str(product_id),
            int(quantity),
            str(Decimal(str(price)).quantize(Decimal("0.01"))),
            json.dumps(user_data or None, sort_keys=True, ensure_ascii=False),
        )
        for product_id, quantity, price, user_data in pairs
    )


async def _take_over_previous_orders(
    db: AsyncSession, user: User, cart_items: list[CartItem]
) -> tuple[Order, Payment] | None:
    """
    Разбирается с неоплаченными заказами покупателя перед новым.

    Каждое нажатие «Оплатить» раньше создавало новый заказ, а прошлый
    оставался висеть и держать товар полчаса. Кошелёк не открылся или его
    закрыли, человек жмёт «Оплатить» ещё раз — и упирается в собственную
    бронь: «Товар уже продан», хотя его никто не покупал. В каталоге вещь
    при этом пропадала, а у продавца значилась «В продаже».

    Теперь:
      * заказ с тем же составом и живым счётом отдаём снова — кошелёк
        откроется на тот же перевод с тем же комментарием, второй брони нет;
      * остальные неоплаченные заказы покупателя снимаем, освобождая товар;
      * если перевод по прошлому заказу уже виден в сети, новый не создаём:
        иначе покупатель заплатил бы дважды.

    Возвращает заказ и счёт, если их можно отдать повторно.
    """
    previous_orders = (
        await db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.user_id == user.id, Order.status == OrderStatus.PENDING)
            .order_by(Order.created_at.desc())
        )
    ).scalars().all()
    if not previous_orders:
        return None

    prices = {
        p.id: p.price_usdt
        for p in (
            await db.execute(
                select(Product).where(Product.id.in_([c.product_id for c in cart_items]))
            )
        ).scalars().all()
    }
    wanted = _contents(
        (c.product_id, c.quantity, prices.get(c.product_id, 0), c.user_data)
        for c in cart_items
    )

    now = datetime.utcnow()
    reusable: tuple[Order, Payment] | None = None
    released: list[uuid.UUID] = []

    for previous in previous_orders:
        payments = (
            await db.execute(select(Payment).where(Payment.order_id == previous.id))
        ).scalars().all()

        if any(p.status in (PaymentStatus.SEEN, PaymentStatus.CONFIRMED) for p in payments):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Оплата предыдущего заказа уже пришла и сейчас подтверждается. "
                    "Подождите минуту — заказ появится в «Мои заказы»."
                ),
            )

        live = next(
            (
                p for p in payments
                if p.status == PaymentStatus.PENDING
                and p.expires_at is not None
                and p.expires_at > now + REUSE_MIN_LEFT
            ),
            None,
        )
        same = _contents(
            (i.product_id, i.quantity, i.price_usdt, i.user_data) for i in previous.items
        ) == wanted

        if reusable is None and live is not None and same:
            reusable = (previous, live)
            continue

        released += await stock_service.release_order(db, previous, expire_payments=True)
        logger.info("[ORDER] Неоплаченный заказ %s снят: покупатель оформляет новый", previous.id)

    if released:
        # Коммит здесь, а не вместе с новым заказом: при повторном
        # использовании нового заказа не будет, а бронь снять всё равно надо
        await db.commit()
        await _broadcast_products(db, released)

    return reusable


async def _shortage_reason(db: AsyncSession, product: Product, quantity: int) -> str:
    """
    Почему товар продавца нельзя купить — честно, а не всегда «уже продан».

    Свои неоплаченные заказы покупателя к этому моменту уже сняты, так что
    бронь здесь — чужая.
    """
    name = product.name_ru

    if product.stock and product.stock > 0:
        return f"«{name}»: в наличии только {product.stock} шт."

    oldest = await stock_service.oldest_reservation(db, product.id)
    if oldest is not None:
        ttl = await settings_service.get_int(db, "order_payment_ttl_min")
        left = (oldest + timedelta(minutes=ttl) - datetime.utcnow()).total_seconds()
        minutes = max(1, math.ceil(left / 60))
        return (
            f"«{name}» сейчас оформляет другой покупатель. Если он не оплатит, "
            f"товар вернётся в продажу примерно через {minutes} мин."
        )

    return f"Товар «{name}» уже продан"


@router.post("", response_model=dict)
async def create_order(
    order_data: OrderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Создаёт ОДИН заказ на всю корзину и выставляет счёт в TON.

    Раньше на каждую позицию корзины создавался отдельный заказ со своим
    инвойсом, а фронт открывал только первый — остальные висели неоплаченными.
    С TON Connect это было бы ещё хуже: каждый заказ требует отдельной подписи
    транзакции в кошельке, то есть корзина из трёх товаров = три подписи.

    Теперь: одна корзина = один заказ = одна транзакция = одна подпись.
    """
    cart_items = (
        await db.execute(select(CartItem).where(CartItem.user_id == user.id))
    ).scalars().all()

    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Условия площадки принимаются до оплаты. 409 с кодом, а не просто 400 —
    # фронт по коду понимает, что надо показать галочку, а не текст ошибки.
    try:
        await terms_service.require(
            db, user, accepted_now=order_data.accept_terms, context="purchase",
        )
    except terms_service.TermsNotAccepted as e:
        raise HTTPException(
            status_code=409,
            detail={"code": "terms_required", "version": e.version, "message": str(e)},
        )

    reusable = await _take_over_previous_orders(db, user, cart_items)
    if reusable is not None:
        previous, payment = reusable
        logger.info("[ORDER] Повторная оплата: отдаём заказ %s заново", previous.id)
        return {
            "order_id": str(previous.id),
            "total_usdt": str(previous.total_usdt),
            "payment": payment_service.build_transaction_request(payment).as_dict(),
        }

    # Резерв держим ровно столько же, сколько живёт счёт: раньше товар
    # резервировался на 3 минуты, а заказ отменялся через 120 — между этими
    # значениями резерв успевал протухнуть на оплаченном заказе.
    reservation_minutes = await settings_service.get_int(db, "order_payment_ttl_min")
    reserved_until = datetime.utcnow() + timedelta(minutes=reservation_minutes)

    order = Order(
        id=uuid.uuid4(),
        user_id=user.id,
        total_usdt=Decimal("0"),
        total_ton=None,
        currency=order_data.currency,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    await db.flush()

    total_usdt = Decimal("0")
    out_of_stock_products: list[str] = []
    updated_products: list[Product] = []

    for cart_item in cart_items:
        product = await db.get(Product, cart_item.product_id)
        if not product:
            continue

        quantity = cart_item.quantity
        item_total = product.price_usdt * quantity
        total_usdt += item_total

        if product.is_p2p:
            # Товар пользователя существует в единственном экземпляре.
            # SELECT ... FOR UPDATE обязателен: без блокировки два покупателя,
            # нажавшие «Оплатить» одновременно, оба увидят stock=1 и оба купят.
            product = (
                await db.execute(
                    select(Product).where(Product.id == product.id).with_for_update()
                )
            ).scalar_one()
            if product.stock is None or product.stock < quantity:
                raise HTTPException(
                    status_code=400,
                    detail=await _shortage_reason(db, product, quantity),
                )
            product.stock -= quantity
            db.add(product)
            updated_products.append(product)

        if product.type == "digital":
            await _reserve_digital_items(
                db, order=order, product=product, quantity=quantity,
                reserved_until=reserved_until,
            )
            if product.stock is not None:
                product.stock -= quantity
                db.add(product)
                updated_products.append(product)
                if product.stock == 0:
                    out_of_stock_products.append(product.name_ru)

        db.add(OrderItem(
            id=uuid.uuid4(),
            order_id=order.id,
            product_id=product.id,
            quantity=quantity,
            price_usdt=product.price_usdt,
            price_ton=product.price_ton,
            product_snapshot={
                "name_ru": product.name_ru,
                "name_en": product.name_en,
                "description_ru": product.description_ru,
                "description_en": product.description_en,
                "content_data": product.content_data,
                "type": product.type,
                "image_url": product.image_url,
                # Фотографии кладём в снапшот вместе с описанием: заказ
                # должен показывать то, что купили, даже если продавец потом
                # сменил картинки или снял товар с продажи
                "images": product.images or [],
                # Признаки P2P попадают в снапшот, а не читаются из products:
                # товар могут снять с продажи или сменить владельца, а условия
                # уже оформленной сделки меняться не должны
                "is_p2p": product.is_p2p,
                "owner_user_id": str(product.owner_user_id) if product.owner_user_id else None,
            },
            user_data=cart_item.user_data,
        ))

    if total_usdt <= 0:
        raise HTTPException(status_code=400, detail="Cart contains no valid products")

    order.total_usdt = total_usdt
    await db.flush()

    payment = await payment_service.create_or_refresh_payment(db, order)
    tx_request = payment_service.build_transaction_request(payment)

    await db.commit()

    # Уведомления и broadcast — после коммита: их падение не должно
    # откатывать уже созданный заказ.
    for product in updated_products:
        await manager.broadcast({
            "type": "product_updated",
            "data": jsonable_encoder(ProductBroadcast.model_validate(product)),
        })
    for name in out_of_stock_products:
        try:
            await telegram_service.send_out_of_stock_notification(name)
        except Exception as e:
            logger.warning("Не удалось отправить уведомление об окончании товара: %s", e)

    return {
        "order_id": str(order.id),
        "total_usdt": str(total_usdt),
        "payment": tx_request.as_dict(),
    }


async def _reserve_digital_items(
    db: AsyncSession,
    *,
    order: Order,
    product: Product,
    quantity: int,
    reserved_until: datetime,
) -> None:
    """
    Резервирует цифровые товары под заказ.

    SELECT ... FOR UPDATE обязателен: без блокировки двое покупателей в один
    момент получают одни и те же экземпляры.
    """
    now = datetime.utcnow()
    stmt = (
        select(DigitalItem)
        .where(
            DigitalItem.product_id == product.id,
            DigitalItem.is_sold == False,  # noqa: E712
            or_(DigitalItem.order_id == None, DigitalItem.reserved_until < now),  # noqa: E711
        )
        .limit(quantity)
        .with_for_update()
    )
    available = (await db.execute(stmt)).scalars().all()

    if len(available) < quantity:
        raise HTTPException(
            status_code=400,
            detail=f"«{product.name_ru}»: столько уже нет в наличии",
        )

    for item in available:
        item.order_id = order.id
        item.reserved_until = reserved_until
        db.add(item)


async def _activate_subscriptions(
    db: AsyncSession,
    order: Order,
    user: User,
    items: list[OrderItem],
    received_nano: int,
) -> list[tuple[str, str]]:
    """
    Активирует подписки из заказа и начисляет авторам их долю.

    Сумма к разделу берётся из фактически поступившего платежа, а не из цены в
    USD: курс на момент оплаты уже зафиксирован, и пересчитывать его заново
    значило бы начислить автору не то, что реально пришло.

    Доля позиции считается пропорционально её стоимости в заказе. Округление
    вниз оставляет копеечный остаток платформе — так автору никогда не
    начислится больше, чем поступило.

    Возвращает пары (название канала, инвайт-ссылка) для уведомления.
    """
    sub_items = [i for i in items if i.product_snapshot.get("type") == "subscription"]
    if not sub_items:
        return []

    total_cents = to_minor(Decimal(str(order.total_usdt)), "USD")

    if not received_nano:
        # Сумму передаёт тот, кто подтвердил платёж. Искать её запросом здесь
        # нельзя: в проекте autoflush=False, и статус платежа, выставленный
        # вызывающим кодом, ещё не записан в БД — запрос ничего не найдёт,
        # и сплит молча не выполнится.
        logger.error(
            "[ORDER] Заказ %s содержит подписки, но сумма платежа не передана — "
            "начисление автору пропущено", order.id,
        )

    invites: list[tuple[str, str]] = []

    for item in sub_items:
        plan_id = (item.product_snapshot.get("content_data") or {}).get("subscription_plan_id")
        if not plan_id:
            logger.error(
                "[ORDER] У позиции подписки %s нет subscription_plan_id — доступ не выдан",
                item.id,
            )
            continue

        plan = await db.get(SubscriptionPlan, uuid.UUID(plan_id))
        if plan is None:
            logger.error("[ORDER] Тариф %s не найден, доступ не выдан", plan_id)
            continue

        channel = await db.get(Channel, plan.channel_id)
        if channel is None:
            logger.error("[ORDER] Канал тарифа %s не найден", plan_id)
            continue

        subscription = await subscription_service.activate_or_extend(
            db, user=user, plan=plan, order_id=order.id, quantity=item.quantity,
        )

        if received_nano and total_cents:
            item_cents = to_minor(
                Decimal(str(item.price_usdt)) * item.quantity, "USD"
            )
            item_nano = received_nano * item_cents // total_cents
            await subscription_service.split_subscription_payment(
                db,
                channel=channel,
                order_id=order.id,
                amount_nano=item_nano,
                key_suffix=str(item.id),
            )

        if subscription.invite_link:
            invites.append((channel.display_title(), subscription.invite_link))

    return invites


async def complete_order(order: Order, db: AsyncSession, received_nano: int = 0):
    """
    Завершает заказ после подтверждённой оплаты.

    received_nano — фактически поступившая сумма. Передаётся явно вызывающим
    кодом: запрашивать её из БД здесь нельзя, потому что статус платежа в этот
    момент ещё не записан (autoflush=False).
    """
    # Update order status
    order.status = OrderStatus.PAID
    order.paid_at = datetime.utcnow()
    
    # Process referral commission
    user = await db.get(User, order.user_id)
    # С суммой в TON — реферальные начисляются в TON, на общий баланс
    await process_referral_commission(db, order, user, received_nano=received_nano)
    
    # Fetch items explicitly to avoid async lazy loading errors
    stmt = select(OrderItem).where(OrderItem.order_id == order.id)
    result = await db.execute(stmt)
    items = result.scalars().all()

    # Оплаченное уходит из корзины. Раньше приложение очищало только свою
    # копию, а строки на сервере оставались: после перезапуска купленный
    # товар (в том числе единственный, которого уже нет) возвращался в
    # корзину. Чистим здесь, а не при создании заказа: отмена неоплаченного
    # заказа возвращает человека в корзину с теми же позициями.
    await db.execute(
        delete(CartItem).where(
            CartItem.user_id == order.user_id,
            CartItem.product_id.in_([item.product_id for item in items]),
        )
    )

    # Заказ считается завершённым только когда по нему нечего доделывать.
    # Услуги ждут ручной обработки админом, P2P — подтверждения получения
    # покупателем. И то и другое оставляет заказ в статусе PAID.
    has_pending_fulfillment = any(
        item.product_snapshot.get("type") == "service"
        or item.product_snapshot.get("is_p2p")
        for item in items
    )
            
    # Finalize Digital Items (Mark as sold, clear reservation)
    stmt = select(DigitalItem).where(DigitalItem.order_id == order.id)
    result = await db.execute(stmt)
    reserved_items = result.scalars().all()
    
    for item in reserved_items:
        item.is_sold = True
        item.reserved_until = None
        db.add(item)

    # Подписки: активируем доступ в канал и делим сумму с автором
    subscription_invites = await _activate_subscriptions(
        db, order, user, items, received_nano
    )

    # P2P: создаём сделки и замораживаем деньги в escrow.
    # Продавцу они не начислены — он получит их после подтверждения получения.
    deals = await deal_service.create_deals_for_order(
        db, order=order, buyer=user, items=items, received_nano=received_nano,
    )

    # Цифровые товары и инструкции выдаются мгновенно — такой заказ закрывается сразу
    if not has_pending_fulfillment:
        order.status = OrderStatus.COMPLETED

    await db.commit()
    
    # Первое сообщение переписки — об оплате. Продавец узнаёт о продаже из
    # уведомления бота об этом сообщении (services/deal_chat_service), а
    # покупателю оно показывает, что чат сделки уже открыт.
    opened = []
    for deal in deals:
        try:
            opened.append((deal, await deal_chat_service.post_system(
                db, deal, "pay", deal_chat_service.pay_text(deal),
            )))
        except Exception as e:
            logger.error("[ORDER] Не удалось открыть чат по сделке #%s: %s", deal.number, e)
    if opened:
        await db.commit()
        for deal, message in opened:
            await deal_chat_service.push_message(deal, message)

    # Ссылки на закрытые каналы отправляем отдельно: ссылка одноразовая и с
    # ограниченным сроком, поэтому она не должна потеряться среди прочих
    # сообщений о покупке.
    for channel_title, invite_link in subscription_invites:
        try:
            await telegram_service.send_message(
                user.telegram_id,
                f"Подписка на «{channel_title}» оформлена.\n\n"
                f"Ссылка для входа (одноразовая, действует сутки):\n{invite_link}",
                parse_mode=None,
            )
        except Exception as e:
            logger.error("[ORDER] Не удалось отправить инвайт-ссылку: %s", e)

    # Send purchase data to user (non-blocking, if fails order still completed)
    try:
        for order_item in items:
            product_name = order_item.product_snapshot.get("name_ru", "Product")
            product_type = order_item.product_snapshot.get("type", "service")
            content_data = order_item.product_snapshot.get("content_data", {})
            quantity = order_item.quantity

            # Подписка: пользователь уже получил ссылку выше, дублировать не надо
            if product_type == "subscription":
                continue
            
            # For digital items, fetch actual purchased items
            digital_items_content = []
            if product_type == "digital":
                stmt = select(DigitalItem).where(
                    DigitalItem.order_id == order.id,
                    DigitalItem.product_id == order_item.product_id
                )
                result = await db.execute(stmt)
                purchased_items = result.scalars().all()
                digital_items_content = [item.content for item in purchased_items]
            
            await telegram_service.send_purchase_data(
                telegram_id=user.telegram_id,
                product_name=product_name,
                product_type=product_type,
                quantity=quantity,
                content_data=content_data,
                digital_items=digital_items_content
            )

            # Notify admin if it's a service order
            if product_type == "service":
                try:
                    user_link = order_item.user_data.get("link", "Не указана") if order_item.user_data else "Не указана"
                    await telegram_service.send_new_service_order_notification(
                        product_name=product_name,
                        user_link=user_link,
                        quantity=quantity
                    )
                except Exception as e:
                    print(f"[ORDER] WARNING: Failed to send admin service notification: {e}")
    except Exception as e:
        print(f"[WEBHOOK] WARNING: Failed to send telegram message: {e}")


@router.get("/admin/all", response_model=list[OrderResponse])
async def get_all_orders(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all orders (admin only)"""
    stmt = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.reviews)
    ).order_by(Order.created_at.desc())
    result = await db.execute(stmt)
    orders = result.scalars().all()
    
    response = []
    for order in orders:
        order_data = OrderResponse.model_validate(order)
        reviewed_product_ids = {r.product_id for r in order.reviews}
        for item in order_data.items:
            item.is_reviewed = item.product_id in reviewed_product_ids
        response.append(order_data)
        
    return response
