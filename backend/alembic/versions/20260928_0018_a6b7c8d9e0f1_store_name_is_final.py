"""Название магазина выбирается один раз и не повторяется

Два правила вместо прежней свободной правки:

  * название занято — второй магазин с таким же именем завести нельзя.
    Уникальность по lower(): «Market» и «market» покупатель не различит,
    а именно на этом и строится подмена чужого магазина;

  * название выбирается один раз. name_locked отмечает магазины, где
    владелец его уже выбрал. У существующих магазинов имя выбирал сам
    владелец при регистрации — их запираем сразу. Пустым флаг остаётся
    только у магазинов, заведённых автоматически при подключении канала:
    там имя подставлено по названию канала, и владелец его ещё не видел.

Витрина площадки под правило «один раз» не попадает: её имя правит
администратор в админке, и это не самоназвание продавца. Уникальности она
подчиняется наравне со всеми — два «Маркета» в каталоге неразличимы.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a6b7c8d9e0f1'
down_revision: Union[str, None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'seller_profiles',
        sa.Column(
            'name_locked', sa.Boolean(),
            nullable=False, server_default=sa.text('false'),
        ),
    )

    # Имя у существующих магазинов выбирал владелец — считаем его выбранным
    op.execute("UPDATE seller_profiles SET name_locked = true")

    # Совпадения развести до индекса, иначе он просто не создастся.
    # Порядок по created_at: первым имя оставляет тот, кто занял его раньше.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY lower(display_name) ORDER BY created_at, id
                   ) AS rn
              FROM seller_profiles
        )
        UPDATE seller_profiles AS sp
           SET display_name = left(sp.display_name, 88) || ' #' || ranked.rn
          FROM ranked
         WHERE sp.id = ranked.id
           AND ranked.rn > 1
        """
    )

    op.execute(
        "CREATE UNIQUE INDEX ix_seller_profiles_name_ci "
        "ON seller_profiles (lower(display_name))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_seller_profiles_name_ci")
    op.drop_column('seller_profiles', 'name_locked')
