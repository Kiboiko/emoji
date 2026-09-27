"""Галерея товара и количество у заявки

Три вещи, которых не хватало:

1. products.images — все фотографии товара. У Product всегда была ровно одна
   картинка (image_url), а заявка принимает до восьми: при публикации
   доезжала только первая, остальные оставались в listing_images и
   покупателю не показывались никогда.

2. product_listings.quantity — сколько единиц товара у продавца. Раньше при
   публикации стоку жёстко проставлялась единица: продавец с десятью
   одинаковыми ключами мог продать только один.

3. Подписки переезжают в магазин автора. Товар тарифа заводился без
   владельца, и в каталоге его автором показывался канал — то есть у автора
   с магазином оказывалось два магазина сразу.

image_url не трогаем: на него смотрят карточки, корзина и снапшоты заказов.
Он остаётся первой фотографией галереи.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'products',
        sa.Column(
            'images', postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        'product_listings',
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
    )

    # Фотографии уже опубликованных заявок — в галерею товара. Порядок тот
    # же, что в кабинете продавца: по sort_order.
    op.execute(
        """
        UPDATE products AS p
           SET images = src.urls
          FROM (
                SELECT l.product_id,
                       jsonb_agg(i.url ORDER BY i.sort_order, i.id) AS urls
                  FROM product_listings AS l
                  JOIN listing_images AS i ON i.listing_id = l.id
                 WHERE l.product_id IS NOT NULL
                 GROUP BY l.product_id
               ) AS src
         WHERE p.id = src.product_id
        """
    )

    # У автора канала должен быть магазин, иначе подписке некуда переезжать.
    # Каналы подключали до этой правки, и своего магазина у большинства
    # авторов нет: кошелёк и согласие с условиями они давали каналу.
    # Название берём по каналу — переименовать можно в настройках магазина.
    op.execute(
        """
        INSERT INTO seller_profiles
               (id, user_id, display_name, payout_wallet, status,
                terms_version, terms_accepted_at, created_at)
        SELECT DISTINCT ON (c.owner_user_id)
               gen_random_uuid(), c.owner_user_id, LEFT(c.title, 100),
               COALESCE(c.payout_wallet, ''), 'ACTIVE',
               c.terms_version, c.terms_accepted_at, NOW()
          FROM channels AS c
         WHERE NOT EXISTS (
               SELECT 1 FROM seller_profiles AS sp
                WHERE sp.user_id = c.owner_user_id
               )
         ORDER BY c.owner_user_id, c.created_at
        """
    )

    # Товары тарифов получают владельца — автора канала. По этому полю
    # витрина находит магазин продавца, и подписка перестаёт быть отдельным
    # магазином.
    op.execute(
        """
        UPDATE products AS p
           SET owner_user_id = c.owner_user_id
          FROM subscription_plans AS sp
          JOIN channels AS c ON c.id = sp.channel_id
         WHERE sp.product_id = p.id
           AND p.owner_user_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE products AS p
           SET owner_user_id = NULL
          FROM subscription_plans AS sp
         WHERE sp.product_id = p.id
        """
    )
    op.drop_column('product_listings', 'quantity')
    op.drop_column('products', 'images')
