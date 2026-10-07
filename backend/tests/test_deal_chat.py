"""
Переписка по сделке в приложении.

Раньше переписка шла через бота, и при двух открытых сделках бот
переспрашивал, кому адресовано сообщение. Теперь у каждой сделки свой чат, а
бот только напоминает о непрочитанном — одним уведомлением на пачку и не
тогда, когда чат открыт.
"""

import io
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select

from models.order import OrderItem
from models.p2p import Deal, DealMessage, DealStatus, MessageDirection, SellerProfile
from routes import admin_p2p
from routes import deals as deal_routes
from routes import internal
from services import deal_chat_service as chat
from services import deal_media
from services.money import to_minor
from services.telegram_service import telegram_service

pytestmark = pytest.mark.asyncio

AMOUNT = to_minor(Decimal("12.5"), "TON")


@pytest.fixture
async def seller(db, user_factory):
    user = await user_factory(username="chat_seller")
    db.add(SellerProfile(
        id=uuid.uuid4(), user_id=user.id,
        display_name="Цифровой угол", payout_wallet="EQSellerWallet",
    ))
    await db.flush()
    return user


@pytest.fixture
async def buyer(db, user_factory):
    return await user_factory(username="chat_buyer")


@pytest.fixture
async def deal(db, buyer, seller, order_factory):
    order = await order_factory(buyer, total_usdt="12.50")
    item = OrderItem(
        id=uuid.uuid4(), order_id=order.id, product_id=None, quantity=1,
        price_usdt=Decimal("12.50"),
        product_snapshot={"name_ru": "Cyberpunk 2077", "type": "p2p", "is_p2p": True,
                          "images": ["/uploads/listings/cp.jpg"]},
    )
    db.add(item)
    await db.flush()
    row = Deal(
        id=uuid.uuid4(), order_id=order.id, order_item_id=item.id,
        buyer_id=buyer.id, seller_id=seller.id, product_name="Cyberpunk 2077",
        amount_nano=AMOUNT, commission_nano=AMOUNT // 50,
        seller_amount_nano=AMOUNT - AMOUNT // 50,
        status=DealStatus.PAID_ESCROW,
        confirm_deadline_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture(autouse=True)
def quiet_sockets():
    """Рассылка по WebSocket в тестах никуда не идёт — проверяем данные, а не сокеты."""
    from utils.websockets import manager

    with patch.object(manager, "send_personal_message", AsyncMock()) as sent:
        yield sent


async def _send(db, deal, user, text):
    return await deal_routes.send_message(deal.id, deal_routes.MessageIn(text=text), user=user, db=db)


def _age(message: DealMessage, seconds: int) -> None:
    """Сдвигает сообщение в прошлое — уведомления ждут паузу после него."""
    message.created_at = datetime.utcnow() - timedelta(seconds=seconds)


class TestSending:

    async def test_participant_writes_and_chat_opens(self, db, deal, buyer):
        dto = await _send(db, deal, buyer, "Ключ подойдёт для Казахстана?")

        assert dto["from"] == "me"
        assert dto["state"] == "sent"
        assert deal.status == DealStatus.CHAT_OPENED
        assert deal.last_message_at is not None

    async def test_outsider_gets_not_found(self, db, deal, user_factory):
        stranger = await user_factory(username="chat_stranger")
        with pytest.raises(HTTPException) as exc:
            await _send(db, deal, stranger, "Привет")
        assert exc.value.status_code == 404

    async def test_closed_chat_refuses(self, db, deal, buyer):
        deal.status = DealStatus.RELEASED
        deal.chat_closed = True
        await db.flush()

        with pytest.raises(HTTPException) as exc:
            await _send(db, deal, buyer, "Ещё вопрос")
        assert exc.value.status_code == 400
        assert "история сохранена" in exc.value.detail

    async def test_flood_is_stopped(self, db, deal, buyer):
        for n in range(chat.FLOOD_LIMIT):
            await chat.post_message(db, deal, buyer, text=f"сообщение {n}")
        await db.flush()

        with pytest.raises(chat.ChatError):
            await chat.post_message(db, deal, buyer, text="ещё одно")


class TestUnreadAndReceipts:

    async def test_counterpart_sees_unread_author_does_not(self, db, deal, buyer, seller):
        await _send(db, deal, buyer, "Здравствуйте!")

        assert (await chat.unread_counts(db, seller)).get(deal.id) == 1
        assert (await chat.unread_counts(db, buyer)).get(deal.id) is None

    async def test_reading_clears_counter_and_doubles_ticks(self, db, deal, buyer, seller):
        await _send(db, deal, buyer, "Здравствуйте!")
        await deal_routes.mark_read(deal.id, user=seller, db=db)

        assert (await chat.unread_counts(db, seller)).get(deal.id) is None
        history = await deal_routes.deal_messages(deal.id, user=buyer, db=db)
        assert history["messages"][-1]["state"] == "read"

    async def test_own_action_is_not_unread_for_actor(self, db, deal, buyer, seller):
        """Продавец нажал «Я отправил» — ему это сообщение незачем подсвечивать."""
        await deal_routes.mark_delivered(deal.id, user=seller, db=db)

        assert (await chat.unread_counts(db, seller)).get(deal.id) is None
        assert (await chat.unread_counts(db, buyer)).get(deal.id) == 1

    async def test_moderator_message_is_unread_for_both(self, db, deal, buyer, seller, user_factory):
        admin = await user_factory(username="chat_admin", is_admin=True)
        await admin_p2p.moderator_message(
            deal.id, admin_p2p.ModeratorMessage(text="Я модератор, разбираю спор"),
            admin=admin, db=db,
        )

        assert (await chat.unread_counts(db, buyer)).get(deal.id) == 1
        assert (await chat.unread_counts(db, seller)).get(deal.id) == 1
        history = await deal_routes.deal_messages(deal.id, user=buyer, db=db)
        assert history["messages"][-1]["from"] == "moderator"


class TestDealCard:

    async def test_buyer_sees_store_seller_sees_nobody(self, db, deal, buyer, seller):
        """Стороны не видят друг друга: так договориться мимо escrow не выйдет."""
        as_buyer = await deal_routes.deal_card(deal.id, user=buyer, db=db)
        as_seller = await deal_routes.deal_card(deal.id, user=seller, db=db)

        assert as_buyer["store"]["name"] == "Цифровой угол"
        assert as_seller["store"] is None
        assert as_buyer["product_image"] == "/uploads/listings/cp.jpg"
        # Подробности для страницы сделки — из снимка покупки
        assert as_buyer["details"]["images"] == ["/uploads/listings/cp.jpg"]
        assert as_buyer["details"]["store"]["deals_completed"] == 0
        assert as_seller["details"]["store"] is None

    async def test_list_shows_last_message_and_unread(self, db, deal, buyer, seller):
        await _send(db, deal, buyer, "Здравствуйте!")

        rows = await deal_routes.my_deals(user=seller, db=db)

        assert rows[0]["unread"] == 1
        assert rows[0]["last_message"]["from"] == "them"
        assert rows[0]["last_message"]["text"] == "Здравствуйте!"

    async def test_short_dispute_reason_from_button_is_accepted(self, db, deal, buyer):
        """Причина выбирается кнопкой: «Другое» короче прежних десяти символов."""
        with patch.object(telegram_service, "send_message", AsyncMock()):
            dto = await deal_routes.open_dispute(
                deal.id, deal_routes.DisputeOpen(reason="Другое"), user=buyer, db=db,
            )
        assert dto["status"] == "disputed"

        last = (
            await db.execute(
                select(DealMessage).where(DealMessage.deal_id == deal.id)
                .order_by(DealMessage.created_at.desc())
            )
        ).scalars().first()
        assert last.kind == "dispute"
        assert "Покупатель открыл спор" in last.text


class TestPresence:
    """«В сети» и «был(а) в сети» в шапке чата."""

    @pytest.fixture
    def online(self):
        """Подключает пользователю «сокет» — менеджеру важен только сам факт."""
        from utils.websockets import manager

        opened: list[tuple[object, str]] = []

        def connect(user):
            socket = object()
            manager.active_connections.setdefault(str(user.id), []).append(socket)
            opened.append((socket, str(user.id)))
            return socket

        yield connect
        for socket, user_id in opened:
            manager.disconnect(socket, user_id)

    async def test_card_shows_counterpart_online(self, db, deal, buyer, seller, online):
        online(seller)

        card = await deal_routes.deal_card(deal.id, user=buyer, db=db)

        assert card["counterpart_online"] is True
        assert card["counterpart_last_seen_at"] is None

    async def test_offline_counterpart_shows_last_seen(self, db, deal, buyer, seller):
        seller.last_seen_at = datetime(2026, 10, 7, 9, 30)
        await db.flush()

        rows = await deal_routes.my_deals(user=buyer, db=db)

        assert rows[0]["counterpart_online"] is False
        assert rows[0]["counterpart_last_seen_at"] == "2026-10-07T09:30:00.000Z"

    async def test_closed_deal_hides_presence(self, db, deal, buyer, seller, online):
        """Писать в закрытую сделку нельзя — и следить за собеседником незачем."""
        online(seller)
        deal.status = DealStatus.RELEASED
        deal.chat_closed = True
        await db.flush()

        card = await deal_routes.deal_card(deal.id, user=buyer, db=db)

        assert card["counterpart_online"] is None
        assert card["counterpart_last_seen_at"] is None

    async def test_minimized_app_goes_offline_for_counterpart(
        self, db, deal, buyer, seller, online, quiet_sockets
    ):
        """Свёрнутый мини-апп держит соединение, но человек на экран не смотрит."""
        from utils.websockets import manager

        socket = online(seller)
        manager.set_active(socket, False)
        await chat.presence_changed(str(seller.id), True, db=db)

        assert manager.is_online(str(seller.id)) is False
        assert seller.last_seen_at is not None
        event, target = quiet_sockets.await_args.args
        assert target == str(buyer.id)
        assert event["type"] == "deal_presence"
        assert event["deal_id"] == str(deal.id)
        assert event["online"] is False
        assert event["last_seen_at"] is not None

    async def test_second_device_does_not_repeat_announcement(
        self, db, deal, seller, online, quiet_sockets
    ):
        online(seller)
        online(seller)
        await chat.presence_changed(str(seller.id), True, db=db)

        quiet_sockets.assert_not_called()


class TestNotifications:

    async def _run(self, db):
        with patch.object(telegram_service, "send_message", AsyncMock()) as sent:
            await chat.notify_unread(db)
        return sent

    async def test_waits_while_chat_may_be_open(self, db, deal, buyer):
        await chat.post_message(db, deal, buyer, text="Здравствуйте!")
        await db.flush()

        sent = await self._run(db)
        sent.assert_not_called()

    async def test_one_notification_per_batch(self, db, deal, buyer, seller):
        first = await chat.post_message(db, deal, buyer, text="Здравствуйте!")
        second = await chat.post_message(db, deal, buyer, text="Ключ подойдёт?")
        _age(first, 60)
        _age(second, 50)
        await db.flush()

        sent = await self._run(db)
        assert sent.await_count == 1
        chat_id, text = sent.await_args.args[:2]
        assert chat_id == seller.telegram_id
        assert "Новые сообщения по сделке" in text and "(2)" in text
        assert "Покупатель: Ключ подойдёт?" in text

        again = await self._run(db)
        again.assert_not_called()

    async def test_buyer_sees_store_name_in_notification(self, db, deal, buyer, seller):
        message = await chat.post_message(db, deal, seller, text="Ваш ключ: `7KQ4M`")
        _age(message, 60)
        await db.flush()

        sent = await self._run(db)
        text = sent.await_args.args[1]
        assert "Цифровой угол: Ваш ключ: 7KQ4M" in text

    async def test_new_batch_after_reading_notifies_again(self, db, deal, buyer, seller):
        now = datetime.utcnow()
        old = await chat.post_message(db, deal, buyer, text="Первое")
        fresh = await chat.post_message(db, deal, buyer, text="Второе")
        # Хронология: «Первое» → уведомление → продавец прочитал → «Второе»
        old.created_at = now - timedelta(seconds=120)
        deal.seller_notified_at = now - timedelta(seconds=90)
        deal.seller_read_at = now - timedelta(seconds=60)
        fresh.created_at = now - timedelta(seconds=30)
        await db.flush()

        sent = await self._run(db)
        assert sent.await_count == 1
        text = sent.await_args.args[1]
        assert "Новое сообщение по сделке" in text and "Второе" in text

    async def test_read_chat_is_silent(self, db, deal, buyer, seller):
        message = await chat.post_message(db, deal, buyer, text="Здравствуйте!")
        _age(message, 60)
        deal.seller_read_at = datetime.utcnow()
        await db.flush()

        sent = await self._run(db)
        sent.assert_not_called()


class TestPhotos:

    @pytest.fixture(autouse=True)
    def media_dir(self, tmp_path, monkeypatch):
        from config import settings
        monkeypatch.setattr(settings, "DEAL_MEDIA_DIR", str(tmp_path))
        return tmp_path

    def _jpeg_with_exif(self) -> bytes:
        image = Image.new("RGB", (3000, 2000), (200, 30, 30))
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"      # производитель камеры
        exif[0x0110] = "PhoneModel X"    # модель
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", exif=exif)
        assert Image.open(io.BytesIO(buffer.getvalue())).getexif()
        return buffer.getvalue()

    async def test_metadata_is_stripped_and_photo_shrunk(self, media_dir):
        """Сведения о телефоне и месте съёмки не должны уйти второй стороне."""
        name = deal_media.save_photo(self._jpeg_with_exif(), uuid.uuid4())

        saved = Image.open(media_dir / name)
        assert not saved.getexif()
        assert max(saved.size) == deal_media.MAX_SIDE

    async def test_not_an_image_is_refused(self):
        with pytest.raises(deal_media.MediaError):
            deal_media.save_photo(b"<svg onload=alert(1)>", uuid.uuid4())

    async def test_signed_link_opens_and_forgery_does_not(self):
        name = deal_media.save_photo(self._jpeg_with_exif(), uuid.uuid4())
        url = deal_media.signed_url(name)
        query = dict(part.split("=") for part in url.split("?")[1].split("&"))

        assert deal_media.resolve(name, int(query["e"]), query["s"]).is_file()
        with pytest.raises(deal_media.MediaError):
            deal_media.resolve(name, int(query["e"]), "0" * 32)
        with pytest.raises(deal_media.MediaError):
            deal_media.resolve(name, int(time.time()) - 10, query["s"])
        with pytest.raises(deal_media.MediaError):
            deal_media.resolve("../../.env", int(query["e"]), query["s"])

    async def test_photo_message_carries_signed_link(self, db, deal, buyer):
        name = deal_media.save_photo(self._jpeg_with_exif(), deal.id)
        message = await chat.post_message(db, deal, buyer, media_path=name)
        await db.flush()

        dto = chat.message_dto(message, "seller", None)
        assert dto["photo_url"].startswith(f"/api/p2p/deal-media/{name}?e=")


class TestRetention:
    """После завершения переписку можно читать ещё chat_retention_days дней."""

    async def _closed(self, db, deal, buyer, *, days_ago: float):
        await _send(db, deal, buyer, "Ключ: `ABC-123`")
        deal.status = DealStatus.RELEASED
        chat.close_chat(deal)
        deal.chat_closed_at = datetime.utcnow() - timedelta(days=days_ago)
        await db.flush()

    async def test_fresh_closed_chat_is_readable(self, db, deal, buyer):
        await self._closed(db, deal, buyer, days_ago=2)

        history = await deal_routes.deal_messages(deal.id, user=buyer, db=db)
        card = await deal_routes.deal_card(deal.id, user=buyer, db=db)

        assert history["expired"] is False
        assert history["messages"]
        assert card["chat_expired"] is False
        assert card["chat_expires_at"] is not None

    async def test_old_chat_disappears_for_both_sides(self, db, deal, buyer, seller):
        await self._closed(db, deal, buyer, days_ago=8)

        for user in (buyer, seller):
            history = await deal_routes.deal_messages(deal.id, user=user, db=db)
            assert history == {"messages": [], "counterpart_read_at": history["counterpart_read_at"],
                                "expired": True}

        card = await deal_routes.deal_card(deal.id, user=seller, db=db)
        assert card["chat_expired"] is True
        assert card["last_message"] is None

    async def test_unread_of_vanished_chat_is_not_counted(self, db, deal, buyer, seller):
        """Иначе значок горел бы вечно: прочитать переписку уже негде."""
        await self._closed(db, deal, buyer, days_ago=8)
        assert (await chat.unread_counts(db, seller)).get(deal.id) is None

    async def test_moderator_still_sees_the_history(self, db, deal, buyer, user_factory):
        await self._closed(db, deal, buyer, days_ago=30)
        admin = await user_factory(username="chat_admin_ret", is_admin=True)

        result = await admin_p2p.deal_conversation(deal.id, admin=admin, db=db)
        assert any("ABC-123" in (m["text"] or "") for m in result["messages"])


class TestLanguages:

    async def test_system_message_has_both_languages(self, db, deal):
        message = await chat.post_system(db, deal, "pay", chat.pay_text(deal))
        await db.flush()

        dto = chat.message_dto(message, "buyer", None)
        assert dto["text"].startswith("Оплата получена: 12.5 TON")
        assert dto["text_en"].startswith("Payment received: 12.5 TON")

    async def test_language_choice_is_saved(self, db, buyer):
        from routes import users as user_routes
        from schemas.user import LanguageIn

        await user_routes.set_language(LanguageIn(language="en"), user=buyer, db=db)
        assert buyer.app_language == "en"

    async def test_notification_follows_recipient_language(self, db, deal, buyer, seller):
        seller.app_language = "en"
        message = await chat.post_message(db, deal, buyer, text="Hello!")
        _age(message, 60)
        await db.flush()

        with patch.object(telegram_service, "send_message", AsyncMock()) as sent:
            await chat.notify_unread(db)

        text = sent.await_args.args[1]
        assert text.startswith(f"New message in deal #{deal.number}")
        assert "Buyer: Hello!" in text
        button = sent.await_args.kwargs["reply_markup"]
        assert button is None or button["inline_keyboard"][0][0]["text"] == "Open chat"

    async def test_old_bot_era_messages_are_cleaned_by_migration(self):
        """Миграция убирает «Пишите сюда…» и переводит известные тексты."""
        import importlib.util
        from pathlib import Path

        path = next(
            (Path(__file__).resolve().parent.parent / "alembic" / "versions")
            .glob("*_e0f1a2b3c4d5_*.py")
        )
        spec = importlib.util.spec_from_file_location("migration_0022", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        ru, en = migration.translate(
            "Оплата получена, деньги удерживаются платформой до подтверждения получения.\n\n"
            "Пишите сюда — сообщения передаются второй стороне через бота, контакты не раскрываются."
        )
        assert "Пишите сюда" not in ru
        assert en.startswith("Payment received.")

        _, en = migration.translate(
            "Продавец отметил отправку. Подтвердите получение, и деньги уйдут продавцу. "
            "Если не подтвердить, сделка закроется автоматически 13 октября."
        )
        assert en.endswith("closes automatically on October 13.")

        assert migration.translate("Что-то незнакомое") == ("Что-то незнакомое", None)


class TestBotRedirect:

    async def test_message_to_bot_gets_chat_buttons(self, db, deal, buyer, monkeypatch):
        """Бот больше не пересылает — он ведёт в чат сделки в приложении."""
        from config import settings
        monkeypatch.setattr(settings, "SITE_URL", "https://shop.example")

        with patch.object(telegram_service, "send_message", AsyncMock()) as sent:
            result = await internal.relay_incoming(
                internal.RelayIn(telegram_user_id=buyer.telegram_id, message={"text": "Привет"}),
                db=db,
            )

        assert result == {"reply": None}
        keyboard = sent.await_args.kwargs["reply_markup"]["inline_keyboard"]
        button = keyboard[0][0]
        assert button["web_app"]["url"] == f"https://shop.example/my/deals/{deal.id}"
        assert f"№{deal.number}" in button["text"]

        stored = (
            await db.execute(select(DealMessage).where(DealMessage.deal_id == deal.id))
        ).scalars().all()
        assert stored == []

    async def test_no_deals_no_buttons(self, db, user_factory):
        lonely = await user_factory(username="chat_lonely")
        result = await internal.relay_incoming(
            internal.RelayIn(telegram_user_id=lonely.telegram_id, message={"text": "Привет"}),
            db=db,
        )
        assert result == {"reply": "У вас нет активных сделок."}
