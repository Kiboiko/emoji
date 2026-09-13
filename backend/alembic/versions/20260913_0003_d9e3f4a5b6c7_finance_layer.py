"""финансовый слой: accounts, ledger_entries, app_settings

Создаёт ядро для денег, на которое лягут TON-оплата, комиссии, escrow,
подписки и рефералка.

Заодно переносит существующие балансы. Раньше единственным «кошельком» было
поле users.referral_earnings типа Float. Float для денег — источник
накапливающейся погрешности, а одного скалярного поля не хватает, когда
получателей несколько (платформа / автор канала / продавец / реферер).

ВАЖНО про валюту переноса. Старые балансы номинированы в USD, новые
начисления пойдут в TON. Пересчитывать историю по сегодняшнему курсу — значит
задним числом менять людям суммы и потом объясняться. Поэтому старые остатки
переносятся КАК USD (отдельная валюта на том же счёте), а TON начнёт
начисляться с нуля. Счёт умеет обе валюты: ключ уникальности —
(владелец, валюта).

Enum'ы хранятся именами в верхнем регистре: SQLAlchemy для Enum(PyEnum)
пишет .name, а не .value (проверено на существующих orders.status).

Revision ID: d9e3f4a5b6c7
Revises: c8d2e3f4a5b6
Create Date: 2026-09-13
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd9e3f4a5b6c7'
down_revision: Union[str, None] = 'c8d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACCOUNT_OWNER_TYPES = ('EXTERNAL', 'PLATFORM', 'USER')

LEDGER_ENTRY_TYPES = (
    'OPENING_BALANCE', 'PAYMENT_IN', 'COMMISSION', 'SELLER_ACCRUAL',
    'AUTHOR_ACCRUAL', 'REFERRAL_ACCRUAL', 'ESCROW_HOLD', 'ESCROW_RELEASE',
    'ESCROW_REFUND', 'WITHDRAWAL_RESERVE', 'WITHDRAWAL_COMPLETE',
    'WITHDRAWAL_CANCEL', 'MANUAL_ADJUST',
)

LEDGER_REF_TYPES = (
    'ORDER', 'DEAL', 'SUBSCRIPTION', 'WITHDRAWAL', 'MIGRATION', 'MANUAL',
)


def upgrade() -> None:
    op.create_table(
        'accounts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('owner_type',
                  sa.Enum(*ACCOUNT_OWNER_TYPES, name='accountownertype',
                          native_enum=False, length=20),
                  nullable=False),
        sa.Column('owner_id', sa.UUID(), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('balance_minor', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('hold_minor', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_type', 'owner_id', 'currency',
                            name='uq_account_owner_currency'),
    )
    op.create_index('ix_accounts_owner', 'accounts', ['owner_type', 'owner_id'])

    op.create_table(
        'ledger_entries',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('hold_delta_minor', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('entry_type',
                  sa.Enum(*LEDGER_ENTRY_TYPES, name='ledgerentrytype',
                          native_enum=False, length=30),
                  nullable=False),
        sa.Column('ref_type',
                  sa.Enum(*LEDGER_REF_TYPES, name='ledgerreftype',
                          native_enum=False, length=20),
                  nullable=False),
        sa.Column('ref_id', sa.UUID(), nullable=True),
        # UNIQUE здесь — единственная надёжная защита от двойного начисления.
        # Проверка "нет ли уже такой записи" в коде не спасает: между проверкой
        # и вставкой пролезает параллельный запрос.
        sa.Column('idempotency_key', sa.String(length=160), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_by_admin_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_admin_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_ledger_idempotency_key'),
    )
    op.create_index('ix_ledger_account_created', 'ledger_entries',
                    ['account_id', 'created_at'])
    op.create_index('ix_ledger_ref', 'ledger_entries', ['ref_type', 'ref_id'])

    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_admin_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by_admin_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('key'),
    )

    _migrate_referral_balances()


def _migrate_referral_balances() -> None:
    """
    Переносит users.referral_earnings (Float, USD) в accounts + ledger_entries.

    Само поле НЕ удаляем: оно ещё отдаётся в API (UserResponse.referral_earnings)
    и читается фронтом. Начиная с этой миграции журнал становится источником
    правды, а поле — денормализованным кешем, который поддерживается в
    актуальном состоянии финансовым слоем. Удалить его можно будет после
    того, как фронт перейдёт на новые эндпоинты.
    """
    bind = op.get_bind()
    now = sa.func.now()

    rows = bind.execute(sa.text(
        "SELECT id, referral_earnings FROM users "
        "WHERE referral_earnings IS NOT NULL AND referral_earnings <> 0"
    )).fetchall()

    if not rows:
        return

    # Внешний счёт: источник переносимых остатков, чтобы двойная запись сошлась
    external_id = uuid.uuid4()
    bind.execute(
        sa.text(
            "INSERT INTO accounts (id, owner_type, owner_id, currency, "
            "balance_minor, hold_minor, created_at, updated_at) "
            "VALUES (:id, 'EXTERNAL', NULL, 'USD', 0, 0, now(), now())"
        ),
        {"id": external_id},
    )

    external_total = 0

    for user_id, earnings in rows:
        # Float -> центы. Через str() и Decimal, чтобы не тащить в перенос
        # погрешность двоичного float (0.1 + 0.2 != 0.3).
        # Округление HALF_UP: при переносе остатков нельзя обсчитать людей.
        cents = int(
            (Decimal(str(earnings)) * 100).to_integral_value(rounding=ROUND_HALF_UP)
        )
        if cents == 0:
            continue

        account_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO accounts (id, owner_type, owner_id, currency, "
                "balance_minor, hold_minor, created_at, updated_at) "
                "VALUES (:id, 'USER', :uid, 'USD', :bal, 0, now(), now())"
            ),
            {"id": account_id, "uid": user_id, "bal": cents},
        )
        bind.execute(
            sa.text(
                "INSERT INTO ledger_entries (id, account_id, currency, amount_minor, "
                "hold_delta_minor, entry_type, ref_type, ref_id, idempotency_key, "
                "comment, created_at) "
                "VALUES (:id, :acc, 'USD', :amt, 0, 'OPENING_BALANCE', 'MIGRATION', "
                "NULL, :key, :comment, now())"
            ),
            {
                "id": uuid.uuid4(),
                "acc": account_id,
                "amt": cents,
                "key": f"migration:d9e3f4a5b6c7:opening:{user_id}",
                "comment": "Перенос остатка referral_earnings из старой схемы",
            },
        )
        external_total += cents

    # Встречная проводка на внешний счёт: сумма всех проводок должна быть 0
    bind.execute(
        sa.text(
            "INSERT INTO ledger_entries (id, account_id, currency, amount_minor, "
            "hold_delta_minor, entry_type, ref_type, ref_id, idempotency_key, "
            "comment, created_at) "
            "VALUES (:id, :acc, 'USD', :amt, 0, 'OPENING_BALANCE', 'MIGRATION', "
            "NULL, :key, :comment, now())"
        ),
        {
            "id": uuid.uuid4(),
            "acc": external_id,
            "amt": -external_total,
            "key": "migration:d9e3f4a5b6c7:opening:external",
            "comment": "Встречная проводка к переносу остатков",
        },
    )
    bind.execute(
        sa.text("UPDATE accounts SET balance_minor = :bal WHERE id = :id"),
        {"bal": -external_total, "id": external_id},
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_index('ix_ledger_ref', table_name='ledger_entries')
    op.drop_index('ix_ledger_account_created', table_name='ledger_entries')
    op.drop_table('ledger_entries')
    op.drop_index('ix_accounts_owner', table_name='accounts')
    op.drop_table('accounts')
