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


async def call_backend(path: str, payload: dict) -> dict | None:
    """
    Запрос к внутреннему API бэкенда.

    Вся логика сделок и маршрутизации живёт там: у бота нет доступа к БД, и
    заводить второе подключение значило бы дублировать модели и ловить
    рассинхрон при миграциях.
    """
    if not INTERNAL_TOKEN:
        logger.warning("INTERNAL_API_TOKEN не задан — запрос %s не отправлен", path)
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{BACKEND_URL}/api/internal/{path}",
                json=payload,
                headers={"X-Internal-Token": INTERNAL_TOKEN},
            )
        if response.status_code >= 400:
            logger.error("Бэкенд отклонил %s: %s %s", path,
                         response.status_code, response.text[:200])
            return None
        return response.json()
    except Exception as e:
        # Падение бэкенда не должно ронять бота
        logger.error("Запрос %s не удался: %s", path, e)
        return None


def deal_keyboard(deal_number: int, role: str) -> InlineKeyboardBuilder:
    """Кнопки действий под сообщением о сделке."""
    builder = InlineKeyboardBuilder()
    if role == "seller":
        builder.button(text="Я отправил товар", callback_data=f"deal:delivered:{deal_number}")
    else:
        builder.button(text="Подтвердить получение", callback_data=f"deal:confirm:{deal_number}")
    builder.button(text="Открыть спор", callback_data=f"deal:dispute:{deal_number}")
    builder.adjust(1)
    return builder


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


@dp.callback_query(lambda c: c.data and c.data.startswith("deal:"))
async def on_deal_action(callback: types.CallbackQuery):
    """Нажатие кнопки действия по сделке."""
    try:
        _, action, number = callback.data.split(":", 2)
    except ValueError:
        await callback.answer("Некорректная кнопка")
        return

    result = await call_backend("deal-action", {
        "telegram_user_id": callback.from_user.id,
        "deal_number": int(number),
        "action": action,
    })

    reply = (result or {}).get("reply") or "Не удалось выполнить действие, попробуйте позже."
    # alert=True для действий с деньгами: всплывающее окно труднее
    # не заметить, чем тост внизу экрана
    await callback.answer(reply, show_alert=True)


@dp.callback_query(lambda c: c.data and c.data.startswith("mod:"))
async def on_moderation_action(callback: types.CallbackQuery):
    """
    Кнопка модерации под уведомлением о новой заявке.

    Права проверяет бэкенд по telegram_user_id: общий секрет подтверждает лишь
    то, что запрос пришёл от бота, а уведомления уходят в админский чат, где
    кнопку может нажать любой участник группы.
    """
    try:
        _, action, listing_id = callback.data.split(":", 2)
    except ValueError:
        await callback.answer("Некорректная кнопка")
        return

    result = await call_backend("moderate-listing", {
        "telegram_user_id": callback.from_user.id,
        "listing_id": listing_id,
        "approve": action == "approve",
    })

    reply = (result or {}).get("reply") or "Не удалось выполнить, попробуйте позже."
    await callback.answer(reply, show_alert=True)

    # answerCallbackQuery умеет показать только текст — Telegram не даёт
    # открыть из него произвольную ссылку (url там принимает только t.me и
    # игры бота, не любой https). Отдельным сообщением с inline-кнопкой это
    # ограничение не действует, поэтому для отказа шлём сообщение с прямой
    # ссылкой на модерацию, а не просто говорим "откройте админку сами".
    if result and result.get("open_admin") and WEBAPP_URL:
        link = InlineKeyboardBuilder()
        link.button(text="Открыть модерацию", url=f"{WEBAPP_URL}/admin/moderation")
        await callback.message.answer(
            "Отклонить с причиной можно в админке:",
            reply_markup=link.as_markup(),
        )

    # Убираем кнопки у обработанной заявки, чтобы её не одобрили повторно
    # и чтобы в чате было видно, что решение принято
    if result and result.get("status"):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as e:
            logger.warning("Не удалось убрать кнопки: %s", e)


@dp.message()
async def on_relay_message(message: types.Message):
    """
    Любое сообщение в личке боту — это реплика в чате сделки.

    Ловим и текст, и вложения: бэкенд пересылает их контрагенту через
    copyMessage, поэтому здесь важно передать сообщение целиком, а не только
    текст.

    Обработчик стоит ПОСЛЕДНИМ: команды и кнопки перехватываются выше.
    """
    if message.chat.type != "private":
        return

    payload = message.model_dump(mode="json", exclude_none=True)

    result = await call_backend("relay", {
        "telegram_user_id": message.from_user.id,
        "message": payload,
    })

    if result is None:
        await message.answer("Сервис временно недоступен, попробуйте позже.")
        return

    reply = result.get("reply")
    if reply:
        await message.answer(reply)


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
