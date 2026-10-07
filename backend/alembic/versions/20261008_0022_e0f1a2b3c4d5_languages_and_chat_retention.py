"""Язык пользователя, английские системные сообщения, срок жизни переписки,
свои названия каналов

  * users.app_language — язык, выбранный в приложении. Раньше выбор жил
    только в памяти приложения и сбрасывался при каждом запуске, а бот о нём
    не знал и писал всем по-русски;
  * deal_messages.text_en — английский текст системного сообщения. Оба
    текста пишутся сразу, приложение показывает нужный;
  * deals.chat_closed_at — когда переписка закрылась. Ещё
    chat_retention_days дней (настройка, по умолчанию 7) её можно прочитать,
    потом она пропадает у сторон. Для уже закрытых сделок берём время
    завершения;
  * channels.title_ru / title_en — название канала, заданное автором. Главнее
    телеграмного, которое перезаписывается при каждой проверке прав бота.

Заодно существующие системные сообщения получают английский текст, а из
сообщений об оплате времён переписки через бота убирается «Пишите сюда —
сообщения передаются второй стороне через бота…»: переписка давно в
приложении, и фраза только путает. Эту правку текста откатить нельзя —
downgrade убирает только колонки.
"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e0f1a2b3c4d5'
down_revision: Union[str, None] = 'd9e0f1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
MONTHS_EN = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

BOT_ERA_TAIL = re.compile(r"\s*Пишите сюда — .*$", re.DOTALL)

PAY = re.compile(r"^Оплата получена: (.+?)\. Деньги удерживаются площадкой до подтверждения получения\.$")
PAY_OLD = re.compile(r"^Оплата получена, деньги удерживаются платформой до подтверждения получения\.$")
SHIP = re.compile(
    r"^Продавец отметил отправку\. Подтвердите получение, и деньги уйдут продавцу\."
    r"(?: Если не подтвердить, сделка закроется автоматически (\d{1,2}) (\w+)\.)?$"
)
DISPUTE = re.compile(r"^(Покупатель|Продавец) открыл спор: «(.*)»\.\n", re.DOTALL)
RESOLVED = re.compile(r"^Спор решён в пользу (продавца|покупателя)[^\n]*(?:\n(.*))?$", re.DOTALL)

DONE = (
    "Покупатель подтвердил получение. Сделка завершена, чат закрыт.",
    "The buyer confirmed receipt. The deal is complete, the chat is closed.",
)
AUTO_DONE = (
    "Срок подтверждения истёк — сделка закрыта автоматически, "
    "деньги переведены продавцу. Чат закрыт.",
    "The confirmation period has expired — the deal closed automatically "
    "and the money went to the seller. The chat is closed.",
)


def translate(text: str) -> tuple[str, str | None]:
    """Русский текст (возможно, исправленный) и английский, если узнали."""
    text = BOT_ERA_TAIL.sub("", text).strip()

    if PAY_OLD.match(text):
        return (
            "Оплата получена. Деньги удерживаются площадкой до подтверждения получения.",
            "Payment received. The marketplace holds the money until receipt is confirmed.",
        )
    if m := PAY.match(text):
        return text, f"Payment received: {m.group(1)}. The marketplace holds the money until receipt is confirmed."
    if m := SHIP.match(text):
        en = "The seller marked the item as sent. Confirm receipt and the money goes to the seller."
        if m.group(1) and m.group(2) in MONTHS_RU:
            month = MONTHS_EN[MONTHS_RU.index(m.group(2))]
            en += f" If you do not confirm, the deal closes automatically on {month} {m.group(1)}."
        return text, en
    if text == DONE[0]:
        return DONE
    if text == AUTO_DONE[0]:
        return AUTO_DONE
    if m := DISPUTE.match(text):
        who = "buyer" if m.group(1) == "Покупатель" else "seller"
        return text, (
            f"The {who} opened a dispute: “{m.group(2)}”.\n"
            "The money stays with the marketplace until a moderator decides. "
            "This conversation will be taken into account."
        )
    if m := RESOLVED.match(text):
        en = (
            "The dispute was resolved in the seller's favour, the money went to the seller."
            if m.group(1) == "продавца" else
            "The dispute was resolved in the buyer's favour, the money went back to the buyer's balance."
        )
        note = (m.group(2) or "").strip()
        return text, f"{en}\n{note}".strip()
    return text, None


def upgrade() -> None:
    op.add_column('users', sa.Column('app_language', sa.String(length=5), nullable=True))
    op.add_column('deal_messages', sa.Column('text_en', sa.Text(), nullable=True))
    op.add_column('deals', sa.Column('chat_closed_at', sa.DateTime(), nullable=True))
    op.add_column('channels', sa.Column('title_ru', sa.String(length=255), nullable=True))
    op.add_column('channels', sa.Column('title_en', sa.String(length=255), nullable=True))

    op.execute(
        "UPDATE deals SET chat_closed_at = "
        "COALESCE(released_at, refunded_at, last_message_at, created_at) "
        "WHERE chat_closed"
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, text FROM deal_messages WHERE direction = 'SYSTEM' AND text IS NOT NULL"
    )).fetchall()
    for message_id, text in rows:
        ru, en = translate(text)
        if ru != text or en is not None:
            bind.execute(
                sa.text("UPDATE deal_messages SET text = :ru, text_en = :en WHERE id = :id"),
                {"ru": ru, "en": en, "id": message_id},
            )


def downgrade() -> None:
    op.drop_column('channels', 'title_en')
    op.drop_column('channels', 'title_ru')
    op.drop_column('deals', 'chat_closed_at')
    op.drop_column('deal_messages', 'text_en')
    op.drop_column('users', 'app_language')
