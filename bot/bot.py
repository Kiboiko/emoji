import asyncio
import logging
import os
import sys

import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBAPP_URL = (os.getenv("WEBAPP_URL") or os.getenv("SITE_URL") or "").strip('"\'')

# Бэкенд внутри docker-сети. Секрет общий, см. backend/routes/internal.py
BACKEND_URL = os.getenv("BACKEND_INTERNAL_URL", "http://backend:8000")
INTERNAL_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")

if not BOT_TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN is not set")
    sys.exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def command_start_handler(message: types.Message, command: CommandObject):
    """Кнопка открытия Mini App + проброс реферального кода."""
    user = message.from_user
    logger.info("/start от %s (@%s, id=%s), args=%s",
                user.full_name, user.username, user.id, command.args)

    if not WEBAPP_URL:
        await message.answer("Магазин временно недоступен: не настроен адрес приложения.")
        return

    start_arg = command.args
    app_url = WEBAPP_URL
    if start_arg:
        separator = "&" if "?" in app_url else "?"
        app_url = f"{app_url}{separator}startapp={start_arg}"

    # Telegram принимает кнопку Mini App только с HTTPS. На локальном стенде
    # адрес http://localhost, и раньше обработчик падал с TelegramBadRequest —
    # пользователь не получал вообще ничего, включая уведомления о покупках.
    # Теперь при не-HTTPS адресе отправляем текст без кнопки.
    if not app_url.startswith("https://"):
        logger.warning("WEBAPP_URL не HTTPS (%s) — кнопка Mini App не добавлена", app_url)
        await message.answer(
            "Бот подключён.\n\n"
            "Кнопка магазина появится, когда приложение будет доступно по HTTPS "
            "(сейчас идёт локальное тестирование).\n\n"
            f"Ваш ID: {user.id}"
        )
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="Открыть магазин", web_app=WebAppInfo(url=app_url))

    await message.answer(
        "Добро пожаловать в интернет магазин цифровых товаров!",
        reply_markup=builder.as_markup(),
    )


@dp.my_chat_member()
async def on_bot_status_changed(update: types.ChatMemberUpdated):
    """
    Бота добавили или убрали из канала.

    Зачем: chat_id закрытого канала иначе никак не узнать — по инвайт-ссылке
    Bot API его не отдаёт, а пересылать пост в сторонний бот ради этого
    неудобно. Поэтому бот сам сообщает ID тому, кто его назначил, — этот ID
    автор вставляет в приложение при подключении канала.
    """
    chat = update.chat
    status = update.new_chat_member.status

    if chat.type not in ("channel", "supergroup", "group"):
        return

    logger.info("Статус бота в %s (%s) изменён на %s", chat.title, chat.id, status)

    if status != "administrator":
        return

    rights = update.new_chat_member
    can_invite = getattr(rights, "can_invite_users", False)
    can_restrict = getattr(rights, "can_restrict_members", False)

    lines = [
        f"Бот добавлен администратором в «{chat.title}».",
        "",
        f"ID канала: {chat.id}",
        "",
        "Права:",
        f"  приглашать участников — {'есть' if can_invite else 'НЕТ'}",
        f"  блокировать участников — {'есть' if can_restrict else 'НЕТ'}",
    ]
    if not (can_invite and can_restrict):
        lines += [
            "",
            "Без обоих прав подписки работать не будут: без первого нельзя "
            "выдать доступ, без второго — отозвать его по истечении срока.",
        ]
    else:
        lines += ["", "Всё готово. Вставьте ID канала в приложении при подключении."]

    try:
        await bot.send_message(update.from_user.id, chr(10).join(lines))
    except Exception as e:
        # Пользователь мог не начинать диалог с ботом — тогда писать ему нельзя
        logger.warning("Не удалось уведомить %s о назначении: %s", update.from_user.id, e)


@dp.chat_member()
async def on_chat_member_update(update: types.ChatMemberUpdated):
    """
    Вход и выход участников закрытых каналов.

    Эти события получает только процесс бота, поэтому он пересылает их
    бэкенду: иначе нельзя отличить «купил подписку, но не перешёл по ссылке»
    от «пользуется каналом», и при разборе жалоб непонятно, был ли доступ.

    ВАЖНО: апдейты chat_member Telegram по умолчанию НЕ присылает — их надо
    явно перечислить в allowed_updates при запуске поллинга (см. main()).
    """
    member = update.new_chat_member.user
    # Логируем сразу, до обращения к бэкенду: если тот недоступен, событие
    # всё равно останется видимым в логах бота
    logger.info(
        "chat_member: %s (@%s, id=%s) в «%s» -> %s",
        member.full_name, member.username, member.id,
        update.chat.title, update.new_chat_member.status,
    )

    if not INTERNAL_TOKEN:
        logger.warning("INTERNAL_API_TOKEN не задан — событие chat_member не отправлено")
        return

    payload = {
        "chat_id": update.chat.id,
        "telegram_user_id": update.new_chat_member.user.id,
        "new_status": update.new_chat_member.status,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{BACKEND_URL}/api/internal/chat-member",
                json=payload,
                headers={"X-Internal-Token": INTERNAL_TOKEN},
            )
        if response.status_code >= 400:
            logger.error("Бэкенд отклонил chat_member: %s %s",
                         response.status_code, response.text[:200])
        else:
            logger.info("chat_member передан: %s -> %s",
                        payload["telegram_user_id"], payload["new_status"])
    except Exception as e:
        # Падение бэкенда не должно ронять бота
        logger.error("Не удалось передать chat_member: %s", e)


async def main():
    logger.info("Bot starting, WebApp URL: %s", WEBAPP_URL)

    await bot.delete_webhook(drop_pending_updates=True)

    # resolve_used_update_types() собирает типы по зарегистрированным
    # хендлерам. Без явного списка Telegram не присылает chat_member вовсе,
    # и выдача доступа работала бы «вслепую».
    allowed = dp.resolve_used_update_types()
    logger.info("Запрашиваемые типы апдейтов: %s", allowed)

    await dp.start_polling(bot, allowed_updates=allowed)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped!")
    except Exception as e:
        print(f"Fatal error: {e}")
