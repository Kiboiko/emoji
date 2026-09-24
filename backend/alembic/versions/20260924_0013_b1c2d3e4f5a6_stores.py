"""Магазины: у каждого товара есть продавец, включая саму площадку

До этого «товар площадки» — это товар без владельца (owner_user_id IS NULL),
и никакого лица у него не было: в витрине он приходил без автора, а страницы,
на которую можно перейти, не существовало.

Площадка становится таким же продавцом, как остальные: отдельная строка в
seller_profiles с пометкой is_platform. Товары к ней при этом НЕ
переподвешиваются — owner_user_id у них остаётся пустым. Это намеренно:
owner_user_id означает «товар конкретного пользователя» и завязан на escrow,
блокировку продавца и выплаты. Проставить его площадке значило бы включить
всю эту машинерию для товаров, которые продаёт сама площадка.

user_id у платформенного магазина пустой — за ним не стоит человек. Колонка
для этого сделана необязательной; уникальность по ней сохраняется, потому что
в PostgreSQL несколько NULL уникальному индексу не мешают.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a0b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'seller_profiles',
        sa.Column('avatar_url', sa.String(length=500), nullable=True),
    )
    op.add_column(
        'seller_profiles',
        sa.Column('description', sa.Text(), nullable=True),
    )
    op.add_column(
        'seller_profiles',
        sa.Column('is_platform', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )

    # За магазином площадки не стоит пользователь
    op.alter_column('seller_profiles', 'user_id', existing_type=sa.UUID(), nullable=True)

    # Магазин площадки заводим здесь, а не лениво при первом обращении:
    # создание строки на GET-запросе — это то, чего мы избегаем во всём
    # остальном коде. payout_wallet пустой: выплаты себе площадка не делает.
    op.execute(
        """
        INSERT INTO seller_profiles (
            id, user_id, display_name, payout_wallet, status, is_platform,
            description, rating_sum, rating_count, deals_completed,
            rejected_streak, created_at
        )
        SELECT gen_random_uuid(), NULL, 'Маркет', '', 'ACTIVE', true,
               'Товары от площадки', 0, 0, 0, 0, now()
        WHERE NOT EXISTS (SELECT 1 FROM seller_profiles WHERE is_platform)
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM seller_profiles WHERE is_platform")
    # Обратно в NOT NULL: к этому моменту строк с пустым user_id не осталось
    op.alter_column('seller_profiles', 'user_id', existing_type=sa.UUID(), nullable=False)
    op.drop_column('seller_profiles', 'is_platform')
    op.drop_column('seller_profiles', 'description')
    op.drop_column('seller_profiles', 'avatar_url')
