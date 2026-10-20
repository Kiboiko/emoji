from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from config import settings


# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.SQL_ECHO,
    future=True,
    # Пул побольше стандартного (5+10): запрос каталога, корзина, сокеты и
    # фоновые задачи тянут соединения одновременно, и при росте числа
    # пользователей очередь за соединением превращалась в лаги. Запас
    # по-прежнему мал рядом с max_connections PostgreSQL (100)
    pool_size=15,
    max_overflow=15,
    # Мёртвое соединение (перезапуск базы, обрыв сети) проверяется перед
    # выдачей: иначе первый запрос после обрыва падал бы 500-й ошибкой
    pool_pre_ping=True,
    pool_recycle=1800,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


# Base class for models
class Base(DeclarativeBase):
    pass


# Dependency for getting database session
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
