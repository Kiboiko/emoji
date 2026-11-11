"""Run the old bot for the isolated stage without replies to obsolete updates."""
import asyncio
from datetime import datetime, timezone
import os
import sys

assert os.environ.get('VITE_BOT_USERNAME') == 'Funshop_bot'
assert os.environ.get('WEBAPP_URL') == 'https://tonmarketplace.duckdns.org'
sys.path.insert(0, '/app')

from aiogram import BaseMiddleware
import bot

started_at = datetime.now(timezone.utc)


class FreshUpdatesOnly(BaseMiddleware):
    async def __call__(self, handler, event, data):
        actual = getattr(event, 'event', event)
        date = getattr(actual, 'date', None)
        if date and date < started_at:
            return None
        return await handler(event, data)


delete_webhook = bot.bot.delete_webhook


async def preserve_queue(**kwargs):
    return await delete_webhook(drop_pending_updates=False)


bot.bot.delete_webhook = preserve_queue
bot.dp.update.outer_middleware(FreshUpdatesOnly())
asyncio.run(bot.main())
