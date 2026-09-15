"""
Релей-чат сделки: маршрутизация и доставка.

Главный риск релея — отправить сообщение не тому человеку. Поэтому основная
часть тестов про resolve_deal: когда бот уверен, куда адресовано сообщение, а
когда обязан переспросить.

Вызовы Telegram замоканы.
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from models.p2p import Deal, DealMessage, DealStatus, MessageDirection
from services import relay_service as relay
from services.telegram_service import TelegramApiError

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def parties(db, user_factory):
    buyer = await user_factory(username="relay_buyer")
    seller = await user_factory(username="relay_seller")
    return buyer, seller


@pytest.fixture
def make_deal(db, order_factory):
    async def make(buyer, seller, *, status=DealStatus.CHAT_OPENED, closed=False, name="Товар"):
        order = await order_factory(buyer)
        deal = Deal(
            id=uuid.uuid4(), order_id=order.id,
            buyer_id=buyer.id, seller_id=seller.id,
            product_name=name,
            amount_nano=1_000, commission_nano=20, seller_amount_nano=980,
            status=status, chat_closed=closed,
            confirm_deadline_at=datetime.utcnow() + timedelta(days=7),
        )
        db.add(deal)
        await db.flush()
        return deal
    return make


class TestResolveDeal:
    async def test_no_deals(self, db, parties):
        buyer, _ = parties
        deal, error = await relay.resolve_deal(db, buyer)
        assert deal is None
        assert "нет активных сделок" in error

    async def test_single_open_deal_is_obvious(self, db, parties, make_deal):
        buyer, seller = parties
        only = await make_deal(buyer, seller)

        deal, error = await relay.resolve_deal(db, buyer)
        assert deal.id == only.id
        assert error is None

    async def test_seller_side_resolves_too(self, db, parties, make_deal):
        buyer, seller = parties
        only = await make_deal(buyer, seller)

        deal, _ = await relay.resolve_deal(db, seller)
        assert deal.id == only.id

    async def test_refuses_to_guess_between_several(self, db, parties, make_deal, user_factory):
        """
        Две открытые сделки и не выбрана активная — бот обязан переспросить.
        Отправить сообщение не тому контрагенту хуже, чем уточнить.
        """
        buyer, seller = parties
        other_seller = await user_factory(username="relay_seller2")
        await make_deal(buyer, seller, name="Клавиатура")
        await make_deal(buyer, other_seller, name="Мышь")

        deal, error = await relay.resolve_deal(db, buyer)

        assert deal is None
        assert "несколько активных сделок" in error
        # В подсказке перечислены обе, чтобы человек понял, из чего выбирать
        assert "Клавиатура" in error and "Мышь" in error

    async def test_active_deal_wins(self, db, parties, make_deal, user_factory):
        buyer, seller = parties
        other_seller = await user_factory(username="relay_seller3")
        await make_deal(buyer, seller)
        chosen = await make_deal(buyer, other_seller)

        await relay.set_active_deal(db, buyer, chosen)
        deal, error = await relay.resolve_deal(db, buyer)

        assert deal.id == chosen.id
        assert error is None

    async def test_reply_overrides_active_deal(self, db, parties, make_deal, user_factory):
        """
        Reply на сообщение контрагента — самый надёжный признак: он
        перекрывает активную сделку.
        """
        buyer, seller = parties
        other_seller = await user_factory(username="relay_seller4")
        replied = await make_deal(buyer, seller)
        active = await make_deal(buyer, other_seller)
        await relay.set_active_deal(db, buyer, active)

        db.add(DealMessage(
            id=uuid.uuid4(), deal_id=replied.id,
            direction=MessageDirection.SELLER_TO_BUYER, sender_id=seller.id,
            text="отправил", delivered_message_id=555,
        ))
        await db.flush()

        deal, _ = await relay.resolve_deal(db, buyer, reply_to_message_id=555)
        assert deal.id == replied.id

    async def test_reply_to_foreign_deal_is_ignored(self, db, parties, make_deal, user_factory):
        """
        Reply на сообщение из чужой сделки не должен давать доступ к ней —
        иначе, угадав message_id, можно было бы писать в чужую переписку.
        """
        buyer, seller = parties
        stranger = await user_factory(username="relay_stranger")
        stranger_seller = await user_factory(username="relay_stranger_seller")
        mine = await make_deal(buyer, seller)
        foreign = await make_deal(stranger, stranger_seller)

        db.add(DealMessage(
            id=uuid.uuid4(), deal_id=foreign.id,
            direction=MessageDirection.SELLER_TO_BUYER, sender_id=stranger_seller.id,
            text="чужое", delivered_message_id=777,
        ))
        await db.flush()

        deal, _ = await relay.resolve_deal(db, buyer, reply_to_message_id=777)
        assert deal.id == mine.id     # не чужая сделка

    async def test_closed_chat_is_not_routable(self, db, parties, make_deal):
        buyer, seller = parties
        await make_deal(buyer, seller, status=DealStatus.RELEASED, closed=True)

        deal, error = await relay.resolve_deal(db, buyer)
        assert deal is None
        assert "нет активных сделок" in error

    async def test_stale_active_deal_falls_back(self, db, parties, make_deal):
        """Активная сделка уже закрыта — берём единственную оставшуюся открытую."""
        buyer, seller = parties
        closed = await make_deal(buyer, seller, status=DealStatus.RELEASED, closed=True)
        still_open = await make_deal(buyer, seller)
        buyer.active_deal_id = closed.id
        await db.flush()

        deal, _ = await relay.resolve_deal(db, buyer)
        assert deal.id == still_open.id

    async def test_outsider_cannot_be_made_active(self, db, parties, make_deal, user_factory):
        buyer, seller = parties
        stranger = await user_factory(username="relay_outsider")
        deal = await make_deal(buyer, seller)

        with pytest.raises(relay.RelayError):
            await relay.set_active_deal(db, stranger, deal)


class TestRelayMessage:
    async def test_text_is_copied_and_stored(self, db, parties, make_deal):
        buyer, seller = parties
        deal = await make_deal(buyer, seller, status=DealStatus.PAID_ESCROW)

        call = AsyncMock(return_value={"message_id": 4242})
        with patch.object(relay, "_call", call):
            record = await relay.relay_message(
                db, deal=deal, sender=buyer,
                message={"message_id": 10, "text": "когда отправите?"},
            )

        method, params = call.await_args.args
        # Именно copyMessage: он не показывает отправителя, в отличие от forward
        assert method == "copyMessage"
        assert params["chat_id"] == seller.telegram_id
        assert params["from_chat_id"] == buyer.telegram_id

        assert record.direction == MessageDirection.BUYER_TO_SELLER
        assert record.text == "когда отправите?"
        assert record.delivered_message_id == 4242

    async def test_first_message_opens_chat(self, db, parties, make_deal):
        buyer, seller = parties
        deal = await make_deal(buyer, seller, status=DealStatus.PAID_ESCROW)

        with patch.object(relay, "_call", AsyncMock(return_value={"message_id": 1})):
            await relay.relay_message(
                db, deal=deal, sender=buyer, message={"message_id": 1, "text": "привет"},
            )

        assert deal.status == DealStatus.CHAT_OPENED

    async def test_photo_file_id_is_kept(self, db, parties, make_deal):
        """
        file_id сохраняется, чтобы админ при разборе спора мог переслать
        вложение себе. Берётся самый крупный размер фото.
        """
        buyer, seller = parties
        deal = await make_deal(buyer, seller)

        message = {
            "message_id": 11,
            "caption": "вот фото",
            "photo": [{"file_id": "small"}, {"file_id": "LARGE"}],
        }
        with patch.object(relay, "_call", AsyncMock(return_value={"message_id": 2})):
            record = await relay.relay_message(db, deal=deal, sender=seller, message=message)

        assert record.media_type == "photo"
        assert record.media_file_id == "LARGE"
        assert record.text == "вот фото"

    async def test_blocked_bot_is_reported_and_message_kept(self, db, parties, make_deal):
        """
        Получатель заблокировал бота. Отправителю говорим честно, а сообщение
        остаётся в истории с ошибкой — для спора важно и то, что человек
        пытался сказать.
        """
        buyer, seller = parties
        deal = await make_deal(buyer, seller)

        blocked = AsyncMock(side_effect=TelegramApiError(
            "copyMessage", "Forbidden: bot was blocked by the user", 403,
        ))
        with patch.object(relay, "_call", blocked):
            with pytest.raises(relay.CounterpartUnavailable):
                await relay.relay_message(
                    db, deal=deal, sender=buyer, message={"message_id": 12, "text": "алло"},
                )

        from sqlalchemy import select
        saved = (
            await db.execute(select(DealMessage).where(DealMessage.deal_id == deal.id))
        ).scalars().one()
        assert saved.text == "алло"
        assert "blocked" in saved.delivery_error

    async def test_closed_chat_rejects_messages(self, db, parties, make_deal):
        buyer, seller = parties
        deal = await make_deal(buyer, seller, status=DealStatus.RELEASED, closed=True)

        with pytest.raises(relay.RelayError):
            await relay.relay_message(
                db, deal=deal, sender=buyer, message={"message_id": 13, "text": "ещё вопрос"},
            )

    async def test_close_chat_clears_active_deal(self, db, parties, make_deal):
        """Иначе следующее сообщение улетит в закрытый чат и вернётся ошибкой."""
        buyer, seller = parties
        deal = await make_deal(buyer, seller)
        buyer.active_deal_id = deal.id
        seller.active_deal_id = deal.id
        await db.flush()

        await relay.close_chat(db, deal)

        assert deal.chat_closed is True
        assert buyer.active_deal_id is None
        assert seller.active_deal_id is None
