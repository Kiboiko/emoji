"""One-time non-financial demo fixtures for the separate real-Telegram stage."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import uuid

assert '@gram-stage-db:5432/stage' in os.environ.get('DATABASE_URL', '')
assert os.environ.get('TON_NETWORK') == 'testnet'
sys.path.insert(0, '/app')

from sqlalchemy import func, select, text
from database import AsyncSessionLocal
import models
from models.user import User
from models.product import Product
from models.category import Category
from models.p2p import SellerProfile
from models.review import Review
from models.giveaway import Giveaway
from services import settings_service, market_ranking_service


async def main():
    async with AsyncSessionLocal() as db:
        assert await db.scalar(text('select current_database()')) == 'stage'
        assert not await db.scalar(select(func.count()).select_from(Product))
        for data in json.loads(Path('/stage-tools/staff.json').read_text()):
            data['id'] = uuid.UUID(data['id'])
            db.add(User(**data))
        roots = [Category(name_ru=ru, name_en=en, sort_order=3-i)
            for i, (ru, en) in enumerate([('Telegram','Telegram'),('Фриланс','Freelance'),('Прочее','Other')])]
        db.add_all(roots)
        await db.flush()
        children = [Category(name_ru=ru, name_en=en, parent_id=roots[0].id, sort_order=3-i)
            for i,(ru,en) in enumerate([('Боты','Bots'),('Подписки','Subscriptions'),('NFT','NFT')])]
        db.add_all(children)
        await db.flush()
        categories = children + roots[1:]
        users = []
        for index in range(100):
            user = User(id=uuid.UUID(int=700000+index), telegram_id=8_800_000_000+index,
                username=f'demo{index}', first_name=f'Тестовый покупатель {index+1}',
                referral_code=f'STAGE{index:05}', language_code='ru',
                photo_url='/uploads/demo-nft.jpg' if index < 3 else None)
            db.add(user)
            users.append(user)
        await db.flush()
        for index in range(20):
            db.add(SellerProfile(id=uuid.UUID(int=800000+index), user_id=users[index].id,
                display_name=f'ТЕСТ Маркет {index+1}', payout_wallet='', name_locked=True,
                avatar_url='/uploads/demo-nft.jpg', description='Демонстрационный магазин. Реальных товаров и выплат нет.',
                home_visible=index < 3, ranking_enabled=index < 3))
        products = []
        for index in range(1000):
            image = f'/uploads/perf/product-{index}.{"png" if index % 30 % 2 else "jpg"}'
            assert Path('/app' + image).exists(), image
            product = Product(id=uuid.UUID(int=900000+index), name_ru=f'ТЕСТ · Товар {index+1}', name_en=f'TEST · Item {index+1}',
                description_ru='Тестовый товар. Платежи только в testnet, реальной поставки нет.',
                description_en='Demo item. Testnet only; no real delivery.',
                price_usdt=Decimal(index % 90 + 1), image_url=image, images=[image],
                category_id=categories[index % len(categories)].id,
                is_active=True, is_p2p=True, owner_user_id=users[index % 20].id,
                stock=10, min_quantity=1, type='service', content_data={},
                created_at=datetime.utcnow()-timedelta(minutes=index))
            db.add(product)
            products.append(product)
        await db.flush()
        for index in range(120):
            db.add(Review(product_id=products[0 if index % 2 else 20].id,
                user_id=users[21 + index % 79].id, text=f'Тестовый отзыв {index+1}',
                rating=5 if index < 100 else 4, created_at=datetime.utcnow()-timedelta(days=index)))
        now = datetime.utcnow()
        db.add(Giveaway(id=uuid.UUID(int=600001), title_ru='ТЕСТ · Plush Pepe #171', title_en='TEST · Plush Pepe #171',
            prize='https://t.me/nft/PlushPepe-171', photo_url='/uploads/demo-nft.jpg',
            start_at=now-timedelta(minutes=1), end_at=now+timedelta(days=3), status='open'))
        db.add(Giveaway(id=uuid.UUID(int=600002), title_ru='ТЕСТ · Завершённый розыгрыш', title_en='TEST · Finished giveaway',
            prize='https://t.me/nft/PlushPepe-171', photo_url='/uploads/demo-nft.jpg',
            start_at=now-timedelta(days=2), end_at=now-timedelta(days=1), status='finished', finished_at=now-timedelta(days=1),
            winner_user_id=users[99].id, public_winner_label='Тестовый участник', public_winner_username='demo99'))
        await db.commit()
        for key,value in {
            'terms_version':'TEST-20261108',
            'terms_text':'Тестовый стенд Gram Market. Все товары и отзывы демонстрационные. Платежи только в testnet. Реальные покупки и выдача призов здесь не выполняются.',
            'terms_text_en':'Gram Market test stage. Demo items and reviews. Testnet payments only. No real purchases or prizes.',
            'commission_p2p_bp':300, 'commission_subscription_bp':300,
            'ton_rate_source':'fixed', 'ton_rate_fixed_usd':'2.50',
        }.items():
            await settings_service.set_setting(db,key,value)
        await market_ranking_service.refresh(db)
        await db.commit()
        print('PUBLIC_STAGE_DATA_READY products=1000 clients=100 stores=20 shared_reviews=120')


asyncio.run(main())
