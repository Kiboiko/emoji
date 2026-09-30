"""Остаток товаров продавцов пересчитывается из фактов

До этой правки сток товара продавца двигали приращениями из разных мест, и
он разъезжался с жизнью: правка количества ставила полное число, не вычитая
проданное, а возврат брони прибавлял и к уже снятому с продажи товару.

С этой версии остаток всегда выводится одинаково (services/stock_service):

    количество по заявке − продано по сделкам − ждёт оплаты

У неодобренной заявки — ноль. Миграция один раз приводит к этому виду всё,
что накопилось, чтобы дальнейшие пересчёты шли от верного значения.

Товары без заявки не трогаются: их остаток ведёт не продавец.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE products AS p
           SET stock = CASE
                   WHEN l.status = 'APPROVED' THEN GREATEST(0,
                       l.quantity
                       - COALESCE((
                           SELECT SUM(COALESCE(oi.quantity, 1))
                             FROM deals d
                             LEFT JOIN order_items oi ON oi.id = d.order_item_id
                            WHERE d.product_id = p.id
                              AND d.status NOT IN ('CANCELLED', 'REFUNDED')
                         ), 0)
                       - COALESCE((
                           SELECT SUM(oi.quantity)
                             FROM order_items oi
                             JOIN orders o ON o.id = oi.order_id
                            WHERE oi.product_id = p.id
                              AND o.status = 'PENDING'
                         ), 0))
                   ELSE 0
               END
          FROM product_listings AS l
         WHERE l.product_id = p.id
           AND p.is_p2p
        """
    )


def downgrade() -> None:
    # Прежние значения были ошибочными, восстанавливать их незачем
    pass
