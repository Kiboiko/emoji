"""
P2P: кабинет продавца и заявки на размещение.

Сделки и переписка по ним — в routes/deals.py, модерация — в routes/admin_p2p.py.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from config import settings
from database import get_db
from models.finance import Account, AccountOwnerType
from models.order import OrderItem
from models.p2p import (
    ListingImage, ListingStatus, ProductListing, SellerProfile, SellerStatus,
)
from models.product import Product
from models.user import User
from services import image_upload, settings_service, stock_service, terms_service
from services.money import from_minor
from utils.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/p2p", tags=["P2P"])

# Допустимые форматы — в services/image_upload.py: только растровые, SVG
# исключён намеренно, он может содержать скрипты
MAX_IMAGES_PER_LISTING = 3


# ---------------------------------------------------------------------------
# Схемы
# ---------------------------------------------------------------------------

class SellerRegister(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=100)
    # Больше не нужен: выплаты идут на кошелёк, подключённый в приложении
    # через TonConnect, в момент вывода. Поле принимается ради старых клиентов
    payout_wallet: Optional[str] = Field(None, max_length=80)
    accept_terms: bool


class SellerUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=2, max_length=100)
    payout_wallet: Optional[str] = Field(None, min_length=10, max_length=80)
    description: Optional[str] = Field(None, max_length=1000)


class ListingCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=500)
    # Английские обязательны: каталог двуязычный, и товар без второго
    # текста показывался англоязычному покупателю по-русски
    name_en: str = Field(..., min_length=3, max_length=500)
    description: str = Field(..., min_length=10, max_length=5000)
    description_en: str = Field(..., min_length=10, max_length=5000)
    # Сколько единиц товара у продавца. По умолчанию одна — так было всегда,
    # пока количество вообще нельзя было указать.
    quantity: int = Field(1, ge=1, le=10000)
    price_usd: Decimal = Field(..., gt=0, max_digits=10, decimal_places=2)
    category_id: Optional[uuid.UUID] = None
    accept_terms: bool


class ListingUpdate(BaseModel):
    """Правка заявки. Любое поле необязательно — меняем только присланные."""
    name: Optional[str] = Field(None, min_length=3, max_length=500)
    name_en: Optional[str] = Field(None, min_length=3, max_length=500)
    description: Optional[str] = Field(None, min_length=10, max_length=5000)
    description_en: Optional[str] = Field(None, min_length=10, max_length=5000)
    quantity: Optional[int] = Field(None, ge=1, le=10000)
    price_usd: Optional[Decimal] = Field(None, gt=0, max_digits=10, decimal_places=2)
    category_id: Optional[uuid.UUID] = None


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------

STORE_NAME_MIN = 3
STORE_NAME_MAX = 20
# Латиница, цифры, пробел и несколько знаков. Русские буквы не принимаются:
# заказчик просил единый вид названий, а кириллицу с латиницей легко
# перепутать — «Marke7» и «Магазин» неразличимы с подменой похожих букв
_STORE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._&-]*$")


def _assert_name_is_valid(name: str) -> None:
    """
    Название магазина: 3–20 символов, латиница, цифры, пробел и . _ & -.

    Проверяется только при выборе названия (регистрация, единственная правка).
    Уже существующие названия не трогаем: магазины с кириллицей остаются как
    были, на них висят отзывы.
    """
    if not STORE_NAME_MIN <= len(name) <= STORE_NAME_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Название магазина — от {STORE_NAME_MIN} до {STORE_NAME_MAX} символов",
        )
    if not _STORE_NAME_RE.fullmatch(name) or "  " in name:
        raise HTTPException(
            status_code=400,
            detail=(
                "Название магазина — только английские буквы, цифры, пробел "
                "и знаки . _ & -"
            ),
        )


async def _assert_name_is_free(
    db: AsyncSession, name: str, *, exclude_id: uuid.UUID | None = None
) -> None:
    """
    Название магазина не должно повторяться.

    Сравнение без учёта регистра: «Market» и «market» покупатель не
    различит, а на этом и строится подмена чужого магазина. Индекс в базе
    тот же самый — проверка здесь нужна ради понятного ответа вместо
    ошибки уникальности.
    """
    stmt = select(SellerProfile.id).where(
        func.lower(SellerProfile.display_name) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(SellerProfile.id != exclude_id)

    if (await db.execute(stmt.limit(1))).scalars().first() is not None:
        raise HTTPException(
            status_code=400,
            detail="Такое название магазина уже занято — придумайте другое",
        )


async def _get_seller(db: AsyncSession, user: User) -> SellerProfile:
    profile = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == user.id))
    ).scalars().first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Сначала зарегистрируйтесь как продавец")
    return profile


def _assert_can_sell(profile: SellerProfile) -> None:
    if profile.status == SellerStatus.BANNED:
        raise HTTPException(status_code=403, detail="Аккаунт продавца заблокирован")
    if profile.status == SellerStatus.RESTRICTED:
        if profile.restricted_until and profile.restricted_until > datetime.utcnow():
            raise HTTPException(
                status_code=403,
                detail=f"Размещение ограничено до {profile.restricted_until:%d.%m.%Y %H:%M}. "
                       f"{profile.restriction_reason or ''}".strip(),
            )


# Статусы, в которых заявку можно править.
#
# PENDING сюда не входит намеренно: пока модератор смотрит заявку, текст под
# ним меняться не должен. APPROVED входит — но правка опубликованного товара
# снимает его с витрины и отправляет на повторную проверку (см.
# _apply_edit_side_effects). Иначе получалась бы подмена: отправить
# безобидный текст, дождаться одобрения и заменить его на что угодно.
EDITABLE_STATUSES = (
    ListingStatus.DRAFT,
    ListingStatus.REJECTED,
    ListingStatus.APPROVED,
    ListingStatus.WITHDRAWN,
)


def _assert_editable(listing: ProductListing) -> None:
    if listing.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Заявка в статусе «{listing.status.value}» — правка недоступна",
        )


async def _apply_edit_side_effects(db: AsyncSession, listing: ProductListing) -> bool:
    """
    Что происходит с товаром, когда правят уже одобренную заявку.

    Товар уходит с витрины, заявка — на повторную модерацию. Возвращает True,
    если это произошло: вызывающему нужно сказать об этом продавцу, иначе он
    решит, что товар просто пропал.
    """
    if listing.status != ListingStatus.APPROVED:
        return False

    if listing.product_id:
        product = await db.get(Product, listing.product_id)
        if product is not None:
            product.is_active = False

    listing.status = ListingStatus.PENDING
    listing.moderation_comment = None
    return True


async def _seller_balance_nano(db: AsyncSession, user: User) -> int:
    """
    Заработок продавца, лежащий на его счёте.

    Читаем напрямую, а не через finance_service.user_account: тот заводит счёт,
    если его нет, а GET-запрос не должен ничего создавать.
    """
    account = (
        await db.execute(
            select(Account).where(
                Account.owner_type == AccountOwnerType.USER,
                Account.owner_id == user.id,
                Account.currency == "TON",
            )
        )
    ).scalars().first()
    return account.balance_minor if account else 0


async def _save_listing_image(upload: UploadFile, subdir: str = "listings") -> str:
    """
    Сохраняет фото объявления с проверками.

    Штатный save_image в routes/products.py не проверяет ни тип, ни размер —
    для товаров площадки это терпимо (их заводит админ), для файлов от
    пользователей нет. Проверка и пережатие — в services/image_upload.py:
    тип по содержимому, уменьшение до разумного размера, без EXIF.
    """
    # +1 байт: так «ровно на лимите» отличается от «больше лимита»
    content = await upload.read(settings.MAX_UPLOAD_SIZE + 1)

    try:
        # Pillow держит процессор: в потоке, чтобы не вставал весь сервер
        data, extension = await run_in_threadpool(
            image_upload.prepare, content, settings.MAX_UPLOAD_SIZE,
        )
    except image_upload.ImageError as e:
        raise HTTPException(status_code=400, detail=str(e))

    file_name = f"{uuid.uuid4()}{extension}"
    directory = Path(settings.UPLOAD_DIR) / subdir
    directory.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(directory / file_name, "wb") as out:
        await out.write(data)

    return f"/uploads/{subdir}/{file_name}"


# ---------------------------------------------------------------------------
# Продавец
# ---------------------------------------------------------------------------

@router.get("/seller/me")
async def seller_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == user.id))
    ).scalars().first()
    if profile is None:
        return {"registered": False}

    return {
        "registered": True,
        "id": str(profile.id),
        "display_name": profile.display_name,
        # Витрина по этому флагу решает, показывать поле имени или надпись
        # «название навсегда»
        "name_locked": profile.name_locked,
        "payout_wallet": profile.payout_wallet,
        "avatar_url": profile.avatar_url,
        "description": profile.description,
        "status": profile.status.value,
        "is_verified": profile.is_verified,
        "restricted_until": (
            profile.restricted_until.isoformat() if profile.restricted_until else None
        ),
        "restriction_reason": profile.restriction_reason,
        "rating": profile.rating,
        "rating_count": profile.rating_count,
        "deals_completed": profile.deals_completed,
        "balance_ton": str(from_minor(await _seller_balance_nano(db, user), "TON")),
    }


@router.patch("/seller/me")
async def update_seller(
    payload: SellerUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Правка витринного имени и кошелька для выплат.

    Кошелёк меняется без ограничений: он используется только при выводе,
    который подтверждает администратор вручную, так что подмена перед выплатой
    ничего не даёт злоумышленнику, зато потеря доступа к старому кошельку —
    обычное дело.

    С названием наоборот: оно выбирается один раз. По названию покупатель
    узнаёт магазин, в котором уже покупал, и оставляет отзывы — свободная
    правка позволяла бы назваться чужим именем после того, как чужая
    репутация набрана, и отзывы оставались бы висеть на другом магазине.
    """
    profile = await _get_seller(db, user)

    if payload.display_name is not None:
        name = payload.display_name.strip()
        if name != profile.display_name:
            if profile.name_locked:
                raise HTTPException(
                    status_code=400,
                    detail="Название магазина менять нельзя — оно выбирается один раз",
                )
            _assert_name_is_valid(name)
            await _assert_name_is_free(db, name, exclude_id=profile.id)
            profile.display_name = name
            profile.name_locked = True
    if payload.payout_wallet is not None:
        profile.payout_wallet = payload.payout_wallet.strip()
    if payload.description is not None:
        profile.description = payload.description.strip() or None

    await db.commit()
    return {
        "display_name": profile.display_name,
        "payout_wallet": profile.payout_wallet,
        "description": profile.description,
    }


@router.post("/seller/me/avatar")
async def upload_seller_avatar(
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Логотип магазина.

    Грузится вручную, а не тянется из Telegram, как у каналов: с личным
    аватаром магазин выглядит аккаунтом, а не магазином.

    Проверки те же, что у фото объявлений: тип по содержимому, а не по
    расширению — и то и другое подделывается тривиально.
    """
    profile = await _get_seller(db, user)
    profile.avatar_url = await _save_listing_image(image, subdir="stores")
    await db.commit()
    return {"avatar_url": profile.avatar_url}


@router.post("/seller/register")
async def register_seller(
    payload: SellerRegister,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not payload.accept_terms:
        raise HTTPException(status_code=400, detail="Необходимо принять условия площадки")

    existing = (
        await db.execute(select(SellerProfile).where(SellerProfile.user_id == user.id))
    ).scalars().first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Вы уже зарегистрированы как продавец")

    name = payload.display_name.strip()
    _assert_name_is_valid(name)
    await _assert_name_is_free(db, name)

    version = await terms_service.record(db, user, context="listing")
    profile = SellerProfile(
        id=uuid.uuid4(),
        user_id=user.id,
        display_name=name,
        # Имя выбрано владельцем — дальше оно не меняется
        name_locked=True,
        payout_wallet=(payload.payout_wallet or "").strip(),
        terms_version=version,
        terms_accepted_at=datetime.utcnow(),
    )
    db.add(profile)
    await db.commit()

    return {"registered": True, "status": profile.status.value}


@router.get("/seller/listings")
async def my_listings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_seller(db, user)
    listings = (
        await db.execute(
            select(ProductListing)
            .options(selectinload(ProductListing.images))
            .where(ProductListing.seller_id == profile.id)
            .order_by(ProductListing.created_at.desc())
        )
    ).scalars().all()

    # Заявка без товара, но с пометкой «опубликовано» — сломанное состояние:
    # товар удалили из админки, внешний ключ обнулил ссылку, а статус остался.
    # Продавец видел живой товар, которого в каталоге нет, и вернуть его в
    # продажу было нечем. Чиним при открытии кабинета: отклонённую заявку
    # можно отправить на проверку заново.
    repaired = False
    for l in listings:
        if l.status == ListingStatus.APPROVED and l.product_id is None:
            l.status = ListingStatus.REJECTED
            l.moderation_comment = (
                "Товар удалён администратором. Отправьте заявку на проверку заново."
            )
            repaired = True
    if repaired:
        await db.commit()

    ttl = await settings_service.get_int(db, "order_payment_ttl_min")

    async def sale_state(l: ProductListing) -> dict:
        """
        Что на самом деле происходит с товаром.

        Статус заявки говорит только о модерации: «одобрено» остаётся и
        когда вещь уже купили, и когда её оформил покупатель и вот-вот
        оплатит. Продавец видел «В продаже», а в каталоге товара не было.
        """
        if l.product_id is None:
            return {"stock": None, "sold": 0, "reserved": 0, "reserved_until": None}

        product = await db.get(Product, l.product_id)
        oldest = await stock_service.oldest_reservation(db, l.product_id)
        return {
            "stock": product.stock if product is not None else None,
            "sold": await stock_service.units_sold(db, l.product_id),
            "reserved": await stock_service.units_reserved(db, l.product_id),
            # В UTC с явной «Z»: без неё браузер прочёл бы время как местное
            "reserved_until": (
                (oldest + timedelta(minutes=ttl)).replace(microsecond=0).isoformat() + "Z"
                if oldest is not None else None
            ),
        }

    return [
        {
            "id": str(l.id),
            "name": l.name,
            "name_en": l.name_en,
            "description": l.description,
            "description_en": l.description_en,
            "quantity": l.quantity,
            "price_usd": str(l.price_usd),
            "status": l.status.value,
            "moderation_comment": l.moderation_comment,
            "product_id": str(l.product_id) if l.product_id else None,
            "category_id": str(l.category_id) if l.category_id else None,
            # Не только url: чтобы удалить фото, фронту нужен его id
            "images": [{"id": str(img.id), "url": img.url} for img in l.images],
            "created_at": l.created_at.isoformat(),
            **(await sale_state(l)),
        }
        for l in listings
    ]


@router.post("/seller/listings")
async def create_listing(
    payload: ListingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Создаёт заявку на размещение товара.

    Антифрод: ограничивается количество заявок, одновременно висящих на
    модерации. Без лимита один человек может завалить очередь сотней заявок
    и модерация встанет.
    """
    if not payload.accept_terms:
        raise HTTPException(status_code=400, detail="Необходимо принять условия площадки")

    profile = await _get_seller(db, user)
    _assert_can_sell(profile)

    max_pending = await settings_service.get_int(db, "p2p_max_pending_listings")
    pending = (
        await db.execute(
            select(ProductListing).where(
                ProductListing.seller_id == profile.id,
                ProductListing.status == ListingStatus.PENDING,
            )
        )
    ).scalars().all()

    if len(pending) >= max_pending:
        raise HTTPException(
            status_code=429,
            detail=f"У вас уже {len(pending)} заявок на модерации (лимит {max_pending}). "
                   f"Дождитесь решения по ним.",
        )

    listing = ProductListing(
        id=uuid.uuid4(),
        seller_id=profile.id,
        category_id=payload.category_id,
        name=payload.name.strip(),
        name_en=payload.name_en.strip(),
        description=payload.description.strip(),
        description_en=payload.description_en.strip(),
        quantity=payload.quantity,
        price_usd=payload.price_usd,
        status=ListingStatus.DRAFT,
    )
    db.add(listing)
    await terms_service.record(db, user, context="listing", ref_type="listing", ref_id=listing.id)
    await db.commit()

    return {"id": str(listing.id), "status": listing.status.value}


@router.post("/seller/listings/{listing_id}/images")
async def upload_listing_image(
    listing_id: uuid.UUID,
    image: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_seller(db, user)
    listing = await _own_listing(db, listing_id, profile)

    _assert_editable(listing)

    count = len(listing.images)
    if count >= MAX_IMAGES_PER_LISTING:
        raise HTTPException(status_code=400, detail=f"Максимум {MAX_IMAGES_PER_LISTING} фото")

    url = await _save_listing_image(image)
    record = ListingImage(id=uuid.uuid4(), listing_id=listing.id, url=url, sort_order=count)
    db.add(record)

    # Картинка — такая же часть карточки, как текст: новая фотография у
    # опубликованного товара тоже идёт через проверку
    remoderating = await _apply_edit_side_effects(db, listing)
    await db.commit()

    return {"id": str(record.id), "url": url, "remoderating": remoderating}


@router.post("/seller/listings/{listing_id}/submit")
async def submit_listing(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_seller(db, user)
    _assert_can_sell(profile)
    listing = await _own_listing(db, listing_id, profile)

    if listing.status not in (ListingStatus.DRAFT, ListingStatus.REJECTED):
        raise HTTPException(status_code=400, detail=f"Заявка уже в статусе {listing.status.value}")
    if not listing.images:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы одно фото")

    listing.status = ListingStatus.PENDING
    listing.moderation_comment = None
    await db.commit()

    from services.telegram_service import telegram_service

    # Кнопки прямо в уведомлении: типовое решение по заявке — «да» или «нет»,
    # и заставлять ради него открывать админку на телефоне незачем. Отказ
    # кнопкой уходит без комментария, поэтому кнопка отказа ведёт в админку,
    # где причину можно написать: без причины продавец не знает, что чинить.
    keyboard = {
        "inline_keyboard": [[
            {"text": "Одобрить", "callback_data": f"mod:approve:{listing.id}"},
            {"text": "Отклонить", "callback_data": f"mod:reject:{listing.id}"},
        ]]
    }

    for chat_id in telegram_service.admin_chat_ids:
        try:
            await telegram_service.send_message(
                chat_id,
                f"Новая заявка на размещение\n"
                f"Продавец: {profile.display_name}\n"
                f"Товар: {listing.name}\n"
                f"Цена: ${listing.price_usd}\n"
                f"Фото: {len(listing.images)}",
                parse_mode=None,
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.warning("[P2P] Не удалось уведомить о заявке: %s", e)

    return {"status": listing.status.value}


@router.patch("/seller/listings/{listing_id}")
async def update_listing(
    listing_id: uuid.UUID,
    payload: ListingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Правка заявки.

    Два сценария. Первый: заявку отклонили с комментарием, и продавец
    исправляет ровно то, на что указал модератор. Второй: товар уже в
    каталоге, но в нём опечатка или сменилась цена — раньше для этого
    приходилось заводить заявку заново, теряя отзывы и историю.

    Правка опубликованного товара снимает его с витрины до повторной
    проверки: показывать непроверенный текст под уже одобренной карточкой
    нельзя.
    """
    profile = await _get_seller(db, user)
    listing = await _own_listing(db, listing_id, profile)
    _assert_editable(listing)

    changed = False
    if payload.name is not None and payload.name.strip() != listing.name:
        listing.name = payload.name.strip()
        changed = True
    # Английские тексты обязательны, поэтому стереть их правкой нельзя:
    # пустая строка из одних пробелов проходит проверку длины, но в каталоге
    # дала бы товар без названия у англоязычного покупателя
    if payload.name_en is not None:
        value = payload.name_en.strip()
        if not value:
            raise HTTPException(status_code=400, detail="Английское название не может быть пустым")
        if value != listing.name_en:
            listing.name_en = value
            changed = True
    if payload.description_en is not None:
        value = payload.description_en.strip()
        if not value:
            raise HTTPException(status_code=400, detail="Английское описание не может быть пустым")
        if value != listing.description_en:
            listing.description_en = value
            changed = True
    if payload.description is not None and payload.description.strip() != listing.description:
        listing.description = payload.description.strip()
        changed = True
    if payload.price_usd is not None and payload.price_usd != listing.price_usd:
        listing.price_usd = payload.price_usd
        changed = True
    if payload.category_id is not None and payload.category_id != listing.category_id:
        listing.category_id = payload.category_id
        changed = True

    # Количество намеренно не считается правкой. Модератор проверяет
    # название, описание и фотографии — остаток на складе к этому отношения
    # не имеет, а повторная проверка сняла бы товар с витрины на сутки из-за
    # того, что продавцу привезли ещё десять штук. Меняем сток сразу.
    #
    # Сток — не новое количество целиком: из него вычитается проданное и
    # то, что сейчас ждёт оплаты. Раньше ставилось всё количество, и после
    # одной продажи в продаже снова оказывались все десять штук.
    if payload.quantity is not None and payload.quantity != listing.quantity:
        taken = await stock_service.units_sold(db, listing.product_id)
        held = await stock_service.units_reserved(db, listing.product_id)
        if payload.quantity < taken + held:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Уже продано {taken} шт." + (f", ещё {held} ждут оплаты" if held else "")
                    + f" — меньше {taken + held} указать нельзя"
                ),
            )
        listing.quantity = payload.quantity
        if listing.product_id:
            product = await db.get(Product, listing.product_id)
            if product is not None:
                product.max_quantity = payload.quantity
                await stock_service.refresh_p2p_stock(db, product.id)

    # Без проверки «а изменилось ли что-нибудь» открытая и сразу закрытая
    # форма снимала бы товар с продажи на ровном месте.
    remoderating = await _apply_edit_side_effects(db, listing) if changed else False

    await db.commit()
    return {
        "id": str(listing.id),
        "status": listing.status.value,
        "remoderating": remoderating,
    }


@router.delete("/seller/listings/{listing_id}")
async def delete_listing(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Удаление заявки.

    Нельзя удалить то, по чему была сделка: на товар ссылаются заказ, платёж и
    отзыв, и удаление оставило бы в истории покупателя пустую строку. Такой
    товар снимается с продажи, а не удаляется.

    Опубликованную заявку тоже не удаляем напрямую: сначала «снять с
    продажи» — так продавец видит, что товар исчез из каталога, отдельным
    действием, а не побочным эффектом удаления.
    """
    profile = await _get_seller(db, user)
    listing = await _own_listing(db, listing_id, profile)

    if listing.status in (ListingStatus.PENDING, ListingStatus.APPROVED):
        raise HTTPException(
            status_code=400,
            detail="Сначала снимите товар с продажи, потом удаляйте",
        )

    if await stock_service.units_sold(db, listing.product_id):
        raise HTTPException(
            status_code=400,
            detail="По товару была сделка — удалить нельзя, историю нужно сохранить",
        )

    # Товар из каталога уносим вместе с заявкой: сделок по нему нет, значит
    # ни заказы, ни отзывы на него не ссылаются.
    if listing.product_id:
        product = await db.get(Product, listing.product_id)
        if product is not None:
            ordered = (
                await db.execute(
                    select(func.count()).select_from(OrderItem)
                    .where(OrderItem.product_id == product.id)
                )
            ).scalar() or 0
            # Неоплаченный заказ сделкой не считается, но строку в истории
            # оставляет — такой товар гасим
            if ordered:
                product.is_active = False
                product.stock = 0
            else:
                await db.delete(product)

    await db.delete(listing)
    await db.commit()
    return {"deleted": True}


@router.delete("/seller/listings/{listing_id}/images/{image_id}")
async def delete_listing_image(
    listing_id: uuid.UUID,
    image_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_seller(db, user)
    listing = await _own_listing(db, listing_id, profile)
    _assert_editable(listing)

    image = next((img for img in listing.images if img.id == image_id), None)
    if image is None:
        raise HTTPException(status_code=404, detail="Фото не найдено")

    # Первое фото — это картинка товара в каталоге, поэтому удаление фото у
    # опубликованной заявки тоже идёт через повторную проверку
    await _apply_edit_side_effects(db, listing)

    # Файл с диска не удаляем: он мог уже уйти в каталог как картинка товара
    # (при одобрении берётся первое фото), и удаление оставило бы битую
    # ссылку. Место под фото стоит дешевле сломанной витрины.
    await db.delete(image)
    await db.commit()
    return {"deleted": True}


@router.post("/seller/listings/{listing_id}/withdraw")
async def withdraw_listing(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Снять одобренный товар с продажи — например, вещь продана где-то ещё.

    Товар из каталога не удаляем, а обнуляем сток: на него могут ссылаться
    прошлые заказы и отзывы.
    """
    profile = await _get_seller(db, user)
    listing = await _own_listing(db, listing_id, profile)

    if listing.status != ListingStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Снять с продажи можно только опубликованный товар")

    if listing.product_id:
        product = await db.get(Product, listing.product_id)
        if product:
            product.stock = 0

    listing.status = ListingStatus.WITHDRAWN
    await db.commit()
    return {"status": listing.status.value}


@router.post("/seller/listings/{listing_id}/republish")
async def republish_listing(
    listing_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Вернуть снятый товар в продажу.

    Повторная модерация не нужна: текст уже проверен и с тех пор не менялся —
    правка после одобрения запрещена (см. _assert_editable).
    """
    profile = await _get_seller(db, user)
    _assert_can_sell(profile)
    listing = await _own_listing(db, listing_id, profile)

    if listing.status != ListingStatus.WITHDRAWN:
        raise HTTPException(status_code=400, detail="Вернуть можно только снятый с продажи товар")

    # Без этой проверки проданную вещь можно было бы выставить снова: после
    # покупки сток и так равен нулю, и «снять — вернуть» вернуло бы его в 1.
    #
    # Возвращаем ровно остаток: из заявленного количества вычитаем то, что
    # уже разобрали. Ставить обратно полное количество нельзя — так продавец
    # с одной вещью продавал бы её снова после каждого «снять — вернуть».
    remaining = listing.quantity - await stock_service.units_sold(db, listing.product_id)
    if remaining <= 0:
        raise HTTPException(
            status_code=400,
            detail="Весь товар по этой заявке продан — вернуть его в продажу нельзя",
        )

    listing.status = ListingStatus.APPROVED
    # Остаток пересчитывается уже при одобренной заявке: из него вычитается
    # и то, что покупатели оформили до снятия и ещё могут оплатить
    if listing.product_id:
        await stock_service.refresh_p2p_stock(db, listing.product_id)

    await db.commit()
    return {"status": listing.status.value}


async def _own_listing(
    db: AsyncSession, listing_id: uuid.UUID, profile: SellerProfile
) -> ProductListing:
    listing = (
        await db.execute(
            select(ProductListing)
            .options(selectinload(ProductListing.images))
            .where(ProductListing.id == listing_id)
        )
    ).scalars().first()
    if listing is None or listing.seller_id != profile.id:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return listing
