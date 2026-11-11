"""Seed the isolated performance copy. Never accepts a production database."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import uuid

sys.path.insert(0, '/app')
assert os.environ.get('DATABASE_URL') == 'postgresql+asyncpg://perf:perf-only@gram-perf-db:5432/perf'

from PIL import Image
from sqlalchemy import select, update, text
from database import AsyncSessionLocal
import models
from models.user import User
from models.product import Product
from models.category import Category
from models.p2p import SellerProfile
from utils.auth import create_access_token
from services.image_variants import build


async def main():
    root = Path('/app/uploads')
    folder = root / 'perf'
    folder.mkdir(exist_ok=True)
    rng = random.Random(20261108)
    images = []
    # Unique file names prevent a shared placeholder from hiding image traffic.
    for index in range(30):
        side = [600, 1280, 2000][index % 3]
        image = Image.frombytes('RGB', (side, side), rng.randbytes(side * side * 3))
        source = folder / f'fixture-{index}.{"png" if index % 2 else "jpg"}'
        image.save(source, quality=85)
        build(root, source)
        images.append(source)
    auth = []
    product_ids = []
    stores = []
    async with AsyncSessionLocal() as db:
        assert await db.scalar(text('select current_database()')) == 'perf'
        assert await db.scalar(text('select count(*) from products where name_en like \'Perf item %\'')) == 0
        categories = list((await db.scalars(select(Category.id).order_by(Category.id))).all())
        assert categories
        await db.execute(update(Product).values(is_active=False))
        users = []
        for index in range(100):
            user = User(id=uuid.UUID(int=700000+index), telegram_id=8_800_000_000+index,
                        username=f'perf{index}', first_name='Performance', referral_code=f'PERF{index:05}',
                        language_code='ru', is_admin=False, is_blocked=False, is_moderator=False, token_version=0)
            db.add(user)
            users.append(user)
            auth.append(create_access_token({'user_id': str(user.id), 'telegram_id': user.telegram_id, 'is_admin': False}))
        await db.flush()
        for index in range(20):
            seller = SellerProfile(id=uuid.UUID(int=800000+index), user_id=users[index].id,
                                   display_name=f'Perf store {index}', payout_wallet='', avatar_url='/uploads/perf/fixture-0.jpg')
            db.add(seller)
            stores.append(str(seller.id))
        for index in range(1000):
            source = images[index % len(images)]
            destination = folder / f'product-{index}{source.suffix}'
            destination.hardlink_to(source)
            # Generate variants through the same code as actual uploads.
            for kind in ['_web', '_thumb']:
                for suffix in ['.jpg', '.webp', '.skip']:
                    variant = root / kind / 'uploads' / source.relative_to(root)
                    variant = variant.with_name(variant.name + suffix)
                    if variant.exists():
                        target = root / kind / 'uploads' / destination.relative_to(root)
                        target = target.with_name(target.name + suffix)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.hardlink_to(variant)
            pid = uuid.UUID(int=900000+index)
            product_ids.append(str(pid))
            db.add(Product(id=pid, name_ru=f'Нагрузка {index+1}', name_en=f'Perf item {index+1}',
                           description_ru=f'Нагрузочный товар {index+1}', description_en=f'Performance fixture {index+1}',
                           price_usdt=Decimal(index % 90 + 1), image_url='/uploads/perf/' + destination.name,
                           images=['/uploads/perf/' + destination.name], category_id=categories[index % len(categories)],
                           type='service', is_top=index % 97 == 0, sort_order=0, is_active=True,
                           is_p2p=True, owner_user_id=users[index % 20].id, stock=10, min_quantity=1,
                           content_data={}, created_at=datetime(2026, 11, 1)-timedelta(minutes=index)))
        await db.commit()
        await db.execute(text('ANALYZE'))
    fixture = {'products': product_ids, 'categories': [str(c) for c in categories], 'stores': stores,
               'tokens': auth, 'seed': 20261108}
    Path('/outbox/fixture.json').write_text(json.dumps(fixture))
    Path('/outbox/dataset.json').write_text(json.dumps({'products': 1000, 'clients': 100, 'stores': 20,
        'unique_image_urls': 1000, 'source_images': 30, 'seed': 20261108,
        'source_sha256': [hashlib.sha256(p.read_bytes()).hexdigest() for p in images]}, indent=2))
    print('DATASET_READY products=1000 clients=100 stores=20 image_urls=1000')

if __name__ == '__main__':
    asyncio.run(main())
