"""Создаёт N пользователей приложения и печатает их токены через запятую (для нагрузочного теста)."""
import asyncio
import random
import sys
import uuid

from sqlalchemy import text

from database import AsyncSessionLocal
from utils.auth import create_access_token


async def main(n: int) -> None:
    tokens = []
    async with AsyncSessionLocal() as s:
        for i in range(n):
            uid, tg = uuid.uuid4(), random.randint(5_000_000_000, 5_900_000_000)
            await s.execute(text(
                "insert into users (id, telegram_id, username, first_name, language_code, is_admin, is_blocked, "
                "referral_code, referral_earnings, created_at, is_moderator, token_version) "
                "values (:id,:tg,:u,'K6','ru',false,false,:rc,0,now(),false,0)"),
                {"id": uid, "tg": tg, "u": f"k6_{i}", "rc": f"K6{uuid.uuid4().hex[:10]}"})
            tokens.append(create_access_token({"user_id": str(uid), "telegram_id": tg, "is_admin": False}))
        await s.commit()
    print(",".join(tokens))


asyncio.run(main(int(sys.argv[1])))
