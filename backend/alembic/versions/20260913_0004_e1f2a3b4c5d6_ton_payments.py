"""ton connect: расширение таблицы payments

Таблица payments существовала в схеме, но не использовалась ни строчкой кода:
при CryptoBot данные инвойса складывались прямо в orders. Теперь это
полноценный журнал платежей в TON.

Старые колонки (amount, external_id) не удаляются и делаются nullable —
в них лежит история платежей до перехода на TON Connect. По той же причине
остаётся orders.cryptobot_invoice_id.

Revision ID: e1f2a3b4c5d6
Revises: d9e3f4a5b6c7
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd9e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PAYMENT_STATUSES = ('PENDING', 'SEEN', 'CONFIRMED', 'UNDERPAID', 'EXPIRED', 'FAILED')


def upgrade() -> None:
    # Старые обязательные колонки становятся необязательными: у TON-платежа
    # нет ни суммы в USD-инвойсе, ни внешнего id провайдера.
    op.alter_column('payments', 'amount',
                    existing_type=sa.Numeric(precision=10, scale=2), nullable=True)
    op.alter_column('payments', 'provider',
                    existing_type=sa.String(length=50),
                    server_default=sa.text("'ton_connect'"), nullable=False)
    op.alter_column('payments', 'currency',
                    existing_type=sa.String(length=10),
                    server_default=sa.text("'TON'"), nullable=False)

    op.add_column('payments', sa.Column('amount_nano', sa.BigInteger(), nullable=True))
    op.add_column('payments', sa.Column('usd_amount', sa.Numeric(precision=12, scale=2), nullable=True))
    # Курс с 9 знаками: округление курса до центов даёт заметную ошибку
    # в итоговой сумме при 9 знаках у TON
    op.add_column('payments', sa.Column('rate_usd_per_ton', sa.Numeric(precision=20, scale=9), nullable=True))
    op.add_column('payments', sa.Column('rate_locked_at', sa.DateTime(), nullable=True))
    op.add_column('payments', sa.Column('expires_at', sa.DateTime(), nullable=True))
    op.add_column('payments', sa.Column('destination_address', sa.String(length=80), nullable=True))
    op.add_column('payments', sa.Column('payment_comment', sa.String(length=64), nullable=True))
    op.add_column('payments', sa.Column('tx_hash', sa.String(length=128), nullable=True))
    op.add_column('payments', sa.Column('tx_lt', sa.BigInteger(), nullable=True))
    op.add_column('payments', sa.Column('from_address', sa.String(length=80), nullable=True))
    op.add_column('payments', sa.Column('received_nano', sa.BigInteger(), nullable=True))
    op.add_column('payments', sa.Column('seen_at', sa.DateTime(), nullable=True))

    # status был свободной строкой — переводим в перечисление.
    # Существующие значения приводим к верхнему регистру: SQLAlchemy для
    # Enum(PyEnum) хранит имя члена, а не значение.
    op.execute("UPDATE payments SET status = upper(status)")
    op.execute("UPDATE payments SET status = 'PENDING' WHERE status NOT IN "
               "('PENDING','SEEN','CONFIRMED','UNDERPAID','EXPIRED','FAILED')")
    op.alter_column(
        'payments', 'status',
        existing_type=sa.String(length=20),
        type_=sa.Enum(*PAYMENT_STATUSES, name='paymentstatus',
                      native_enum=False, length=20),
        existing_nullable=False,
    )

    # UNIQUE — не украшение, а защита от подмены и двойного зачёта:
    # совпадение комментариев означало бы зачёт чужого платежа, а повтор
    # tx_hash — выдачу товара дважды за один перевод.
    op.create_unique_constraint('uq_payments_comment', 'payments', ['payment_comment'])
    op.create_unique_constraint('uq_payments_tx_hash', 'payments', ['tx_hash'])

    op.create_index('ix_payments_status_expires', 'payments', ['status', 'expires_at'])
    op.create_index('ix_payments_order', 'payments', ['order_id'])


def downgrade() -> None:
    op.drop_index('ix_payments_order', table_name='payments')
    op.drop_index('ix_payments_status_expires', table_name='payments')
    op.drop_constraint('uq_payments_tx_hash', 'payments', type_='unique')
    op.drop_constraint('uq_payments_comment', 'payments', type_='unique')

    op.alter_column(
        'payments', 'status',
        existing_type=sa.Enum(*PAYMENT_STATUSES, name='paymentstatus',
                              native_enum=False, length=20),
        type_=sa.String(length=20),
        existing_nullable=False,
    )

    for column in (
        'seen_at', 'received_nano', 'from_address', 'tx_lt', 'tx_hash',
        'payment_comment', 'destination_address', 'expires_at',
        'rate_locked_at', 'rate_usd_per_ton', 'usd_amount', 'amount_nano',
    ):
        op.drop_column('payments', column)

    op.alter_column('payments', 'currency',
                    existing_type=sa.String(length=10), server_default=None)
    op.alter_column('payments', 'provider',
                    existing_type=sa.String(length=50),
                    server_default=sa.text("'cryptobot'"))
    op.alter_column('payments', 'amount',
                    existing_type=sa.Numeric(precision=10, scale=2), nullable=False)
