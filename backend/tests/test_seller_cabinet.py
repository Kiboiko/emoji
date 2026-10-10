"""
Кабинет продавца: правка заявок, фото, снятие и возврат товара в продажу.

Ключевой тест здесь — republish_refuses_sold_item. Товар продавца существует в
одном экземпляре, и пара «снять с продажи — вернуть» не должна обнулять факт
покупки: иначе проданную вещь можно выставить снова и получить второго
оплатившего покупателя.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.category import Category
from models.p2p import (
    Deal, DealStatus, ListingImage, ListingStatus, ProductListing, SellerProfile,
)
from models.product import Product
from routes import p2p
from services import finance_service as fin
from services.money import to_minor

pytestmark = pytest.mark.asyncio

TON = "TON"


@pytest.fixture
async def category(db):
    row = Category(id=uuid.uuid4(), name_ru="Вещи", name_en="Items")
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def seller_user(db, user_factory):
    user = await user_factory(username="cabinet_seller")
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=user.id,
        display_name="Seller", payout_wallet="UQSellerWallet0000",
    ))
    await db.flush()
    return user


@pytest.fixture
async def listing_factory(db, seller_user, category):
    """Заявка с одним фото — как её видит бэкенд после загрузки картинки."""
    async def make(status=ListingStatus.DRAFT, with_product=False):
        profile = (await db.execute(
            select(SellerProfile).where(SellerProfile.user_id == seller_user.id)
        )).scalars().one()

        listing = ProductListing(
            id=uuid.uuid4(), seller_id=profile.id, category_id=category.id,
            name="Клавиатура", description="Механическая, почти новая",
            price_usd=Decimal("50.00"), status=status,
        )
        db.add(listing)
        await db.flush()

        db.add(ListingImage(
            id=uuid.uuid4(), listing_id=listing.id,
            url="/uploads/listings/a.jpg", sort_order=0,
        ))

        if with_product:
            product = Product(
                id=uuid.uuid4(), name_ru=listing.name, name_en=listing.name,
                description_ru=listing.description, description_en=listing.description,
                price_usdt=listing.price_usd, image_url="/uploads/listings/a.jpg",
                category_id=category.id, type="p2p", min_quantity=1, max_quantity=1,
                stock=1, content_data={}, owner_user_id=seller_user.id, is_p2p=True,
            )
            db.add(product)
            await db.flush()
            listing.product_id = product.id

        await db.flush()
        await db.refresh(listing, ["images"])
        return listing

    return make


# ---------------------------------------------------------------------------
# Правка заявки
# ---------------------------------------------------------------------------

async def test_edit_rejected_listing(db, seller_user, listing_factory):
    """Отказ модератора чинится правкой, а не заведением заявки заново."""
    listing = await listing_factory(status=ListingStatus.REJECTED)

    await p2p.update_listing(
        listing.id,
        p2p.ListingUpdate(name="Клавиатура Keychron", price_usd=Decimal("45.00")),
        user=seller_user, db=db,
    )

    await db.refresh(listing)
    assert listing.name == "Клавиатура Keychron"
    assert listing.price_usd == Decimal("45.00")
    # Описание не присылали — оно не должно затереться
    assert listing.description == "Механическая, почти новая"


async def test_edit_blocked_after_submit(db, seller_user, listing_factory):
    """
    Заявку на модерации править нельзя: иначе можно отправить безобидный
    текст, дождаться одобрения и подменить содержимое.
    """
    listing = await listing_factory(status=ListingStatus.PENDING)

    with pytest.raises(HTTPException) as exc:
        await p2p.update_listing(
            listing.id, p2p.ListingUpdate(name="Другое название"),
            user=seller_user, db=db,
        )
    assert exc.value.status_code == 400


async def test_edit_after_approval_returns_to_moderation(db, seller_user, listing_factory):
    """
    Правка опубликованного товара разрешена, но стоит публикации.

    Раньше правка после одобрения была запрещена совсем, и опечатка в
    названии означала «заводи заявку заново» с потерей отзывов. Защита от
    подмены осталась другой: товар уходит с витрины до повторной проверки, а не
    показывает непроверенный текст под одобренной карточкой.
    """
    listing = await listing_factory(status=ListingStatus.APPROVED, with_product=True)

    result = await p2p.update_listing(
        listing.id, p2p.ListingUpdate(description="Подменённое описание товара"),
        user=seller_user, db=db,
    )

    assert result["remoderating"] is True
    await db.refresh(listing)
    assert listing.status == ListingStatus.PENDING

    product = await db.get(Product, listing.product_id)
    assert product.is_active is False, "товар с непроверенным текстом остался в каталоге"


async def test_untouched_edit_does_not_unpublish(db, seller_user, listing_factory):
    """
    Открытая и сразу закрытая форма не должна снимать товар с продажи.

    Фронт присылает все поля формы целиком, а не только изменённые, так что
    без сравнения со старыми значениями любое сохранение убирало бы товар из
    каталога на ровном месте.
    """
    listing = await listing_factory(status=ListingStatus.APPROVED, with_product=True)

    result = await p2p.update_listing(
        listing.id,
        p2p.ListingUpdate(name=listing.name, description=listing.description),
        user=seller_user, db=db,
    )

    assert result["remoderating"] is False
    await db.refresh(listing)
    assert listing.status == ListingStatus.APPROVED

    product = await db.get(Product, listing.product_id)
    assert product.is_active is True


async def test_foreign_listing_is_not_found(db, listing_factory, user_factory):
    """Чужая заявка не должна даже подтверждать своё существование."""
    listing = await listing_factory()
    stranger = await user_factory(username="stranger")
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=stranger.id,
        display_name="Чужой", payout_wallet="UQStrangerWallet00",
    ))
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await p2p.update_listing(
            listing.id, p2p.ListingUpdate(name="Захват"), user=stranger, db=db,
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Фото
# ---------------------------------------------------------------------------

async def test_delete_image(db, seller_user, listing_factory):
    listing = await listing_factory()
    image_id = listing.images[0].id

    await p2p.delete_listing_image(listing.id, image_id, user=seller_user, db=db)

    left = (await db.execute(
        select(ListingImage).where(ListingImage.listing_id == listing.id)
    )).scalars().all()
    assert left == []


async def test_delete_image_blocked_on_pending(db, seller_user, listing_factory):
    listing = await listing_factory(status=ListingStatus.PENDING)

    with pytest.raises(HTTPException) as exc:
        await p2p.delete_listing_image(
            listing.id, listing.images[0].id, user=seller_user, db=db,
        )
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Снятие и возврат в продажу
# ---------------------------------------------------------------------------

async def test_withdraw_hides_product(db, seller_user, listing_factory):
    """Товар не удаляем, а обнуляем сток: на него ссылаются заказы и отзывы."""
    listing = await listing_factory(status=ListingStatus.APPROVED, with_product=True)

    await p2p.withdraw_listing(listing.id, user=seller_user, db=db)

    await db.refresh(listing)
    product = await db.get(Product, listing.product_id)
    assert listing.status == ListingStatus.WITHDRAWN
    assert product.stock == 0


async def test_republish_returns_product(db, seller_user, listing_factory):
    listing = await listing_factory(status=ListingStatus.APPROVED, with_product=True)
    await p2p.withdraw_listing(listing.id, user=seller_user, db=db)

    await p2p.republish_listing(listing.id, user=seller_user, db=db)

    await db.refresh(listing)
    product = await db.get(Product, listing.product_id)
    assert listing.status == ListingStatus.APPROVED
    assert product.stock == 1


async def test_republish_refuses_sold_item(db, seller_user, listing_factory, order_factory, user_factory):
    """
    Проданную вещь нельзя вернуть в продажу.

    После покупки сток и так равен нулю, поэтому без этой проверки пара
    «снять — вернуть» выставила бы уже проданный товар заново, и второй
    покупатель заплатил бы за то, чего у продавца больше нет.
    """
    listing = await listing_factory(status=ListingStatus.APPROVED, with_product=True)
    buyer = await user_factory(username="cabinet_buyer")
    order = await order_factory(buyer, total_usdt="50.00")

    db.add(Deal(
        id=uuid.uuid4(), order_id=order.id,
        buyer_id=buyer.id, seller_id=seller_user.id,
        product_id=listing.product_id, product_name=listing.name,
        amount_nano=to_minor(Decimal("10"), TON),
        status=DealStatus.PAID_ESCROW,
    ))
    await db.flush()

    await p2p.withdraw_listing(listing.id, user=seller_user, db=db)

    with pytest.raises(HTTPException) as exc:
        await p2p.republish_listing(listing.id, user=seller_user, db=db)
    assert exc.value.status_code == 400

    product = await db.get(Product, listing.product_id)
    assert product.stock == 0


async def test_republish_allowed_after_cancelled_deal(db, seller_user, listing_factory, order_factory, user_factory):
    """Отменённая сделка вещь не забрала — продавать её снова можно."""
    listing = await listing_factory(status=ListingStatus.APPROVED, with_product=True)
    buyer = await user_factory(username="cabinet_buyer_2")
    order = await order_factory(buyer, total_usdt="50.00")

    db.add(Deal(
        id=uuid.uuid4(), order_id=order.id,
        buyer_id=buyer.id, seller_id=seller_user.id,
        product_id=listing.product_id, product_name=listing.name,
        amount_nano=to_minor(Decimal("10"), TON),
        status=DealStatus.CANCELLED,
    ))
    await db.flush()

    await p2p.withdraw_listing(listing.id, user=seller_user, db=db)
    await p2p.republish_listing(listing.id, user=seller_user, db=db)

    product = await db.get(Product, listing.product_id)
    assert product.stock == 1


async def test_withdraw_requires_approved(db, seller_user, listing_factory):
    listing = await listing_factory(status=ListingStatus.DRAFT)

    with pytest.raises(HTTPException) as exc:
        await p2p.withdraw_listing(listing.id, user=seller_user, db=db)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Профиль
# ---------------------------------------------------------------------------

async def test_profile_shows_earnings(db, seller_user):
    """Продавец должен видеть, сколько ему начислено."""
    account = await fin.user_account(db, seller_user.id, TON)
    await fin.deposit_from_external(
        db, account=account, amount_minor=to_minor(Decimal("24.5"), TON),
        ref_type=fin.LedgerRefType.DEAL, ref_id=uuid.uuid4(),
    )
    await db.flush()

    data = await p2p.seller_profile(user=seller_user, db=db)
    assert data["balance_ton"] == "24.5"


async def test_profile_without_account_shows_zero(db, seller_user):
    """GET не должен заводить счёт — у нового продавца его просто нет."""
    data = await p2p.seller_profile(user=seller_user, db=db)

    assert data["balance_ton"] == "0"
    from models.finance import Account, AccountOwnerType
    accounts = (await db.execute(
        select(Account).where(
            Account.owner_type == AccountOwnerType.USER,
            Account.owner_id == seller_user.id,
        )
    )).scalars().all()
    assert accounts == []


async def test_update_payout_wallet(db, seller_user):
    await p2p.update_seller(
        p2p.SellerUpdate(payout_wallet="UQNewWalletAddress123"),
        user=seller_user, db=db,
    )

    profile = (await db.execute(
        select(SellerProfile).where(SellerProfile.user_id == seller_user.id)
    )).scalars().one()
    assert profile.payout_wallet == "UQNewWalletAddress123"
    # Имя не присылали — оно не должно затереться
    assert profile.display_name == "Seller"


# ---------------------------------------------------------------------------
# Английское название
# ---------------------------------------------------------------------------

async def test_listing_keeps_english_name(db, seller_user, listing_factory):
    listing = await listing_factory(status=ListingStatus.DRAFT)

    await p2p.update_listing(
        listing.id,
        p2p.ListingUpdate(name_en="Mechanical keyboard"),
        user=seller_user, db=db,
    )

    assert listing.name_en == "Mechanical keyboard"


async def test_english_name_cannot_be_wiped(db, seller_user, listing_factory):
    """
    Английские тексты обязательны, поэтому стереть их правкой нельзя. Строка
    из пробелов проходит проверку длины, но в каталоге дала бы товар без
    названия у англоязычного покупателя.
    """
    listing = await listing_factory(status=ListingStatus.DRAFT)
    listing.name_en = "Keyboard"
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await p2p.update_listing(
            listing.id,
            p2p.ListingUpdate(name_en="   "),
            user=seller_user, db=db,
        )

    assert exc.value.status_code == 400
    assert listing.name_en == "Keyboard"


async def test_listing_keeps_english_description(db, seller_user, listing_factory):
    listing = await listing_factory(status=ListingStatus.DRAFT)

    await p2p.update_listing(
        listing.id,
        p2p.ListingUpdate(description_en="Mechanical, almost new"),
        user=seller_user, db=db,
    )

    assert listing.description_en == "Mechanical, almost new"


async def test_quantity_edit_keeps_listing_on_sale(db, seller_user, listing_factory):
    """
    Правка количества не отправляет товар на повторную модерацию.

    Модератор проверяет название, описание и фотографии — остаток на складе
    к этому отношения не имеет. Иначе продавец, которому привезли ещё
    десять штук, терял витрину на время проверки.
    """
    listing = await listing_factory(status=ListingStatus.APPROVED, with_product=True)

    result = await p2p.update_listing(
        listing.id, p2p.ListingUpdate(quantity=7), user=seller_user, db=db,
    )

    assert result["remoderating"] is False
    await db.refresh(listing)
    assert listing.status == ListingStatus.APPROVED
    assert listing.quantity == 7

    product = await db.get(Product, listing.product_id)
    assert product.stock == 7
    assert product.max_quantity == 7
    assert product.is_active is True


async def test_republish_returns_only_unsold_units(
    db, seller_user, listing_factory, order_factory, user_factory,
):
    """
    Возврат в продажу отдаёт остаток, а не всё заявленное количество.

    Проверка «была ли сделка» отвечала на этот вопрос только для товара в
    одном экземпляре. С количеством такой ответ ничего не значит: продав
    один ключ из трёх, продавец должен мочь вернуть на витрину два.
    """
    listing = await listing_factory(status=ListingStatus.APPROVED, with_product=True)
    listing.quantity = 3
    buyer = await user_factory(username="partial_buyer")
    order = await order_factory(buyer, total_usdt="50.00")

    db.add(Deal(
        id=uuid.uuid4(), order_id=order.id,
        buyer_id=buyer.id, seller_id=seller_user.id,
        product_id=listing.product_id, product_name=listing.name,
        amount_nano=to_minor(Decimal("10"), TON),
        status=DealStatus.PAID_ESCROW,
    ))
    await db.flush()

    await p2p.withdraw_listing(listing.id, user=seller_user, db=db)
    await p2p.republish_listing(listing.id, user=seller_user, db=db)

    product = await db.get(Product, listing.product_id)
    assert product.stock == 2


async def test_deleting_product_returns_listing_to_the_seller(db, listing_factory, user_factory):
    """
    Товар удалён из админки — заявка не остаётся «опубликованной».

    Ссылка на товар обнуляется внешним ключом, а статус нет: продавец видел
    в кабинете живой товар, которого в каталоге уже не было, и вернуть его
    в продажу было нечем.
    """
    from routes import products as products_routes

    listing = await listing_factory(status=ListingStatus.APPROVED, with_product=True)
    admin = await user_factory(username="catalog_admin", is_admin=True)
    product_id = listing.product_id

    await products_routes.delete_product(str(product_id), admin=admin, db=db)

    await db.refresh(listing)
    assert listing.status == ListingStatus.REJECTED
    assert listing.product_id is None
    assert "удалён" in (listing.moderation_comment or "")


# ---------------------------------------------------------------------------
# Название магазина
# ---------------------------------------------------------------------------

async def test_chosen_store_name_cannot_be_changed(db, seller_user):
    """
    Название выбирается один раз.

    По нему покупатель узнаёт магазин, в котором уже покупал, и на нём же
    висят отзывы: свободная правка позволяла бы назваться чужим именем
    после того, как чужая репутация набрана.
    """
    profile = (await db.execute(
        select(SellerProfile).where(SellerProfile.user_id == seller_user.id)
    )).scalars().one()
    profile.name_locked = True
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await p2p.update_seller(
            p2p.SellerUpdate(display_name="Other name"), user=seller_user, db=db,
        )

    assert exc.value.status_code == 400
    await db.refresh(profile)
    assert profile.display_name == "Seller"


async def test_auto_created_store_can_be_named_once(db, seller_user):
    """
    Магазин, заведённый при подключении канала, владелец не называл: имя там
    подставлено по каналу. Один раз назвать его он вправе — но только один.
    """
    profile = (await db.execute(
        select(SellerProfile).where(SellerProfile.user_id == seller_user.id)
    )).scalars().one()
    profile.name_locked = False
    await db.flush()

    await p2p.update_seller(
        p2p.SellerUpdate(display_name="My Market"), user=seller_user, db=db,
    )
    await db.refresh(profile)
    assert profile.display_name == "My Market"
    assert profile.name_locked is True

    with pytest.raises(HTTPException):
        await p2p.update_seller(
            p2p.SellerUpdate(display_name="Once more"), user=seller_user, db=db,
        )


async def test_store_name_cannot_repeat_someone_elses(db, seller_user, user_factory):
    """Два магазина с одним именем в каталоге неразличимы."""
    newcomer = await user_factory(username="second_seller")

    with pytest.raises(HTTPException) as exc:
        await p2p.register_seller(
            p2p.SellerRegister(
                display_name="SELLER",   # тот же, но другим регистром
                payout_wallet="UQOtherWallet00000",
                accept_terms=True,
            ),
            user=newcomer, db=db,
        )

    assert exc.value.status_code == 400
    assert "занято" in exc.value.detail


@pytest.mark.parametrize("name", [
    "Магазин",          # кириллица
    "Shop Мир",         # латиница пополам с кириллицей
    "ab",               # короче трёх
    "A" * 21,           # длиннее двадцати
    "Shop  Two",        # два пробела подряд
    "-Shop",            # начинается со знака
    "Shop<script>",     # служебные символы
])
async def test_store_name_rejects_bad_names(db, user_factory, name):
    """Название — 3–20 символов, только английские буквы и цифры."""
    newcomer = await user_factory(username=f"n_{abs(hash(name)) % 10**8}")

    with pytest.raises(HTTPException) as exc:
        await p2p.register_seller(
            p2p.SellerRegister(display_name=name, accept_terms=True),
            user=newcomer, db=db,
        )

    assert exc.value.status_code == 400
    assert "Название магазина" in exc.value.detail


@pytest.mark.parametrize("name", ["Fun Shop", "Shop_24", "A&B-store", "Abc", "x" * 20])
async def test_store_name_accepts_good_names(db, user_factory, name):
    newcomer = await user_factory(username=f"g_{abs(hash(name)) % 10**8}")

    result = await p2p.register_seller(
        p2p.SellerRegister(display_name=name, accept_terms=True),
        user=newcomer, db=db,
    )

    assert result["registered"] is True


async def test_listing_accepts_no_more_than_three_photos():
    """Объявление принимает три фото: больше — отказ с понятным текстом."""
    assert p2p.MAX_IMAGES_PER_LISTING == 3
