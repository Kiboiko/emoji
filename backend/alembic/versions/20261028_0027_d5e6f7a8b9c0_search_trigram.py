"""Триграммные индексы для поиска по каталогу

Только добавление: расширение pg_trgm и четыре индекса, данные не меняются.

Поиск в каталоге — это lower(колонка) LIKE '%слово%' по названию и описанию на
двух языках. С таким шаблоном (подстрока с любого места) обычный индекс не
помогает, и каждый поисковый запрос читал все товары: 52 мс на 5000 товарах
против 5–8 мс у остальных запросов, а на пятидесяти тысячах — полсекунды.
Триграммный GIN-индекс по тому же выражению lower(колонка) ускоряет именно
такие шаблоны; текст запроса менять не нужно.

Короткие запросы (меньше трёх букв) индекс не использует — для них остаётся
чтение таблицы, как и раньше.

pg_trgm — «доверенное» расширение (PostgreSQL 13+) и входит в стандартный
образ postgres: создать его может владелец базы, суперпользователь не нужен.
Но расширения может не быть на хостинге или в урезанной сборке — тогда
миграция НЕ падает (иначе приложение не запустилось бы: оно требует
актуальной схемы), а пропускает индексы с предупреждением. Поиск при этом
работает, как раньше, просто медленнее на большом каталоге.

Индексы названы …_trgm: alembic/env.py не даёт autogenerate предлагать их
удаление (в моделях их нет).
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COLUMNS = ('name_ru', 'name_en', 'description_ru', 'description_en')


def upgrade() -> None:
    index_sql = "\n".join(
        f"        CREATE INDEX IF NOT EXISTS ix_products_{column}_trgm "
        f"ON products USING gin (lower({column}) gin_trgm_ops);"
        for column in COLUMNS
    )
    # Один блок: подтранзакция внутри EXCEPTION откатывает только неудачное
    # создание расширения, остальная миграция остаётся целой
    op.execute(f"""
    DO $$
    BEGIN
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
{index_sql}
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'pg_trgm недоступно (%): индексы поиска пропущены, поиск работает без них', SQLERRM;
    END
    $$;
    """)


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.execute(f"DROP INDEX IF EXISTS ix_products_{column}_trgm")
    # Расширение не удаляем: им могут пользоваться другие индексы, а оно безвредно
