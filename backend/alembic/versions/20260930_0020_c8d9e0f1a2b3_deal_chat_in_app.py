"""Переписка по сделке переезжает из бота в приложение

Бот больше не пересылает сообщения между личками сторон: при двух открытых
сделках он переспрашивал, кому адресовано сообщение, и приходилось отвечать
реплаем. Теперь у каждой сделки своя переписка в мини-аппе, а бот только
присылает уведомление с кнопкой, открывающей нужный чат.

Что нужно базе:

  * deal_messages.kind — вид системного сообщения (оплата, отправка,
    завершение, спор, решение): по нему чат рисует значок;
  * deal_messages.media_path — фото из приложения. Файл лежит вне
    публичной папки uploads и отдаётся только по подписанной ссылке:
    в чате присылают скриншоты аккаунтов, ключи и логины;
  * deals.last_message_at — порядок списка сделок и выборка для уведомлений;
  * deals.{buyer,seller}_read_at — до какого момента сторона прочитала
    переписку: счётчики непрочитанных и двойные галочки;
  * deals.{buyer,seller}_notified_at — когда бот последний раз напомнил
    стороне о непрочитанном: несколько сообщений подряд дают одно
    уведомление, а не по штуке на каждое.

users.active_deal_id удаляется: он был нужен только боту, чтобы угадывать
сделку для сообщения без реплая.

Прежняя переписка считается прочитанной: иначе у всех старых сделок разом
зажглись бы счётчики, а бот разослал бы уведомления о давних сообщениях.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('deal_messages', sa.Column('kind', sa.String(length=20), nullable=True))
    op.add_column('deal_messages', sa.Column('media_path', sa.String(length=255), nullable=True))

    for column in (
        'last_message_at', 'buyer_read_at', 'seller_read_at',
        'buyer_notified_at', 'seller_notified_at',
    ):
        op.add_column('deals', sa.Column(column, sa.DateTime(), nullable=True))
    op.create_index('ix_deals_last_message', 'deals', ['last_message_at'])

    op.execute(
        """
        UPDATE deals AS d
           SET last_message_at = m.last_at
          FROM (SELECT deal_id, MAX(created_at) AS last_at
                  FROM deal_messages GROUP BY deal_id) AS m
         WHERE m.deal_id = d.id
        """
    )
    op.execute(
        """
        UPDATE deals
           SET buyer_read_at = COALESCE(last_message_at, created_at),
               seller_read_at = COALESCE(last_message_at, created_at)
        """
    )

    # Значок у старых системных сообщений — по их началу: текст писался
    # одним местом и не менялся
    for kind, prefix in (
        ('pay', 'Оплата получена'),
        ('ship', 'Продавец отметил отправку'),
        ('done', 'Покупатель подтвердил'),
        ('dispute', 'Открыт спор'),
        ('resolved', 'Спор решён'),
    ):
        op.execute(
            sa.text(
                "UPDATE deal_messages SET kind = :kind "
                "WHERE direction = 'SYSTEM' AND text LIKE :prefix"
            ).bindparams(kind=kind, prefix=prefix + '%')
        )

    op.drop_constraint('users_active_deal_id_fkey', 'users', type_='foreignkey')
    op.drop_column('users', 'active_deal_id')


def downgrade() -> None:
    op.add_column('users', sa.Column('active_deal_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'users_active_deal_id_fkey', 'users', 'deals',
        ['active_deal_id'], ['id'], ondelete='SET NULL',
    )

    op.drop_index('ix_deals_last_message', table_name='deals')
    for column in (
        'last_message_at', 'buyer_read_at', 'seller_read_at',
        'buyer_notified_at', 'seller_notified_at',
    ):
        op.drop_column('deals', column)

    op.drop_column('deal_messages', 'media_path')
    op.drop_column('deal_messages', 'kind')
