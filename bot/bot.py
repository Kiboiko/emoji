import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Configure logging
logging.basicConfig(level=logging.INFO)

# Get settings
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Try WEBAPP_URL first, then SITE_URL as fallback
WEBAPP_URL = os.getenv("WEBAPP_URL") or os.getenv("SITE_URL")
if not WEBAPP_URL:
    # If URLs are provided with quotes in .env, strip them
    if os.getenv("WEBAPP_URL"): WEBAPP_URL = os.getenv("WEBAPP_URL").strip('"\'')
    if os.getenv("SITE_URL"): WEBAPP_URL = WEBAPP_URL or os.getenv("SITE_URL").strip('"\'')

if not BOT_TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN is not set")
    sys.exit(1)


# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Handlers
@dp.message(CommandStart())
async def command_start_handler(message: types.Message, command: CommandObject):
    """
    This handler receives messages with `/start` command
    """
    if not WEBAPP_URL:
        await message.answer("Error: WEBAPP_URL not configured.")
        return

    # Extract start parameter (e.g., ref_12345)
    start_arg = command.args
    logging.info(f"[BOT] Received /start command. Args: {start_arg}")
    
    # Construct URL with startapp parameter if argument exists
    app_url = WEBAPP_URL
    if start_arg:
        # Determine separator (? or &)
        separator = "&" if "?" in app_url else "?"
        app_url = f"{app_url}{separator}startapp={start_arg}"
    
    logging.info(f"[BOT] Generated WebApp URL: {app_url}")

    builder = InlineKeyboardBuilder()
    builder.button(
        text="Открыть магазин", 
        web_app=WebAppInfo(url=app_url)
    )
    
    await message.answer(
        "Добро пожаловать в интернет магазин цифровых товаров!",
        reply_markup=builder.as_markup()
    )

async def main():
    print(f"Starting bot with WebApp URL: {WEBAPP_URL}")
    print("Bot polling started...")
    
    try:
        # Delete webhook to ensure polling works
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped!")
    except Exception as e:
        print(f"Fatal error: {e}")
