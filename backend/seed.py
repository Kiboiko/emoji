import asyncio
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from config import settings
from models import Product, Category  # реестр моделей: нужен полный импорт

# Раньше здесь было settings.DATABASE_URL.replace("postgres", "127.0.0.1"),
# что ломало URL: подстрока "postgres" встречается и в схеме "postgresql+asyncpg://",
# и адрес превращался в "127.0.0.1ql+asyncpg://..." — скрипт падал на разборе URL.
# Берём адрес как есть: внутри docker хост "postgres" резолвится сам,
# снаружи достаточно подставить нужный DATABASE_URL в окружении.
DATABASE_URL = settings.DATABASE_URL

engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def seed_data():
    async with AsyncSessionLocal() as session:
        print("Creating categories...")
        # Check if categories exist
        
        cat1_id = uuid.uuid4()
        cat2_id = uuid.uuid4()

        category1 = Category(
            id=cat1_id,
            name_ru="Стриминг",
            name_en="Streaming",
            sort_order=1
        )
        category2 = Category(
            id=cat2_id,
            name_ru="Социальные сети",
            name_en="Social Media",
            sort_order=2
        )

        session.add(category1)
        session.add(category2)
        
        print("Creating products...")
        
        products = [
            Product(
                id=uuid.uuid4(),
                name_ru="Premium Account Netflix",
                name_en="Premium Account Netflix",
                description_ru="Подписка на 1 месяц с гарантией",
                description_en="1 month subscription with warranty",
                price_usdt=9.99,
                price_ton=2.5,
                image_url="/product-dog.jpg",
                category_id=cat1_id,
                is_top=True,
                type="digital",
                min_quantity=1
            ),
            Product(
                id=uuid.uuid4(),
                name_ru="Spotify Premium",
                name_en="Spotify Premium",
                description_ru="Годовая подписка на музыкальный сервис",
                description_en="1 year subscription music service",
                price_usdt=15.99,
                price_ton=4.0,
                image_url="/product-dog.jpg",
                category_id=cat1_id,
                is_top=False,
                type="digital",
                min_quantity=1
            ),
            Product(
                id=uuid.uuid4(),
                name_ru="YouTube Boosting",
                name_en="YouTube Boosting",
                description_ru="1000 подписчиков на ваш канал. Быстрый старт.",
                description_en="1000 subscribers to your channel. Fast start.",
                price_usdt=12.50,
                price_ton=3.0,
                image_url="/product-dog.jpg",
                category_id=cat2_id,
                is_top=True,
                type="service",
                min_quantity=1000,
                max_quantity=10000
            ),
            Product(
                id=uuid.uuid4(),
                name_ru="Instagram Likes",
                name_en="Instagram Likes",
                description_ru="500 лайков на фото. Живые пользователи.",
                description_en="500 likes on photo. Real users.",
                price_usdt=7.99,
                price_ton=2.0,
                image_url="/product-dog.jpg",
                category_id=cat2_id,
                is_top=False,
                type="service",
                min_quantity=100,
                max_quantity=5000
            ) 
        ]

        for p in products:
            session.add(p)

        await session.commit()
        print("Data seeded successfully!")

if __name__ == "__main__":
    asyncio.run(seed_data())
