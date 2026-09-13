"""
Инфраструктура тестов.

Тесты работают с ОТДЕЛЬНОЙ базой (по умолчанию имя рабочей базы + суффикс
`_test`), чтобы случайный прогон не задел данные разработки. Схема создаётся
из метаданных моделей: для тестов это быстрее и надёжнее прогона всей цепочки
миграций, а сами миграции проверяются отдельно (см. docs/STAGE-1-REPORT.md).

Каждый тест выполняется во внешней транзакции, которая откатывается после —
тесты не видят данных друг друга и не требуют очистки.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from database import Base  # noqa: E402
import models  # noqa: E402,F401  — регистрация всех мапперов


def _test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        return url
    base, _, name = settings.DATABASE_URL.rpartition("/")
    return f"{base}/{name}_test"


TEST_DATABASE_URL = _test_database_url()


# Собственная фикстура event_loop не нужна: в pytest-asyncio 1.x цикл задаётся
# через asyncio_default_*_loop_scope в pytest.ini (оба выставлены в session).


@pytest.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine) -> AsyncSession:
    """
    Сессия внутри транзакции, которая откатывается после теста.

    join_transaction_mode="create_savepoint" нужен, чтобы commit() внутри
    тестируемого кода не завершал внешнюю транзакцию, а откатывался вместе
    с ней.
    """
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )()
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest.fixture
async def user_factory(db):
    """Создаёт пользователей — почти каждому тесту нужен владелец счёта."""
    import uuid as _uuid
    from models.user import User

    created = 0

    async def make(**kwargs) -> User:
        nonlocal created
        created += 1
        user = User(
            id=_uuid.uuid4(),
            telegram_id=kwargs.pop("telegram_id", 900_000_000 + created),
            username=kwargs.pop("username", f"test_user_{created}"),
            first_name=kwargs.pop("first_name", "Test"),
            referral_code=kwargs.pop("referral_code", f"TESTCODE{created}"),
            **kwargs,
        )
        db.add(user)
        await db.flush()
        return user

    return make
