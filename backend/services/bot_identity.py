"""
Проверка при старте: чей токен бота лежит в настройках.

Telegram подписывает данные входа токеном того бота, из которого открыто
приложение. Если токен в .env принадлежит другому боту, подпись не сходится у
КАЖДОГО входа: в журнале доступа это просто россыпь 401, а человек видит
приложение без аккаунта и невнятные ошибки при любом действии. Так и вышло
после переезда на новый сервер: в .env остался токен чужого бота, и неделю
никто не мог войти, а сервис при этом оставался «здоровым».

Теперь это видно в журнале сразу при запуске. Проверка ничего не ломает:
любая ошибка только пишется в журнал.
"""

import logging

from config import settings
from services.telegram_service import TelegramApiError, _call

logger = logging.getLogger(__name__)


def _same_bot(actual: str, configured: str) -> bool:
    return actual.lstrip("@").lower() == configured.lstrip("@").lower()


async def check_bot_identity() -> str | None:
    """Имя бота, которому принадлежит токен, или None. Исключений не бросает."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("[CONFIG] TELEGRAM_BOT_TOKEN не задан: вход через Telegram работать не будет")
        return None

    try:
        me = await _call("getMe", {})
    except TelegramApiError as exc:
        logger.error(
            "[CONFIG] Telegram не принял токен бота (%s). Вход через Telegram работать не будет: "
            "проверьте TELEGRAM_BOT_TOKEN в .env", exc.description,
        )
        return None
    except Exception as exc:  # noqa: BLE001 — сеть может быть недоступна при старте, это не авария
        logger.warning("[CONFIG] Не удалось проверить токен бота: %s", type(exc).__name__)
        return None

    username = me.get("username") or ""
    logger.info("[CONFIG] Токен принадлежит боту @%s (id %s)", username, me.get("id"))

    configured = (settings.VITE_BOT_USERNAME or "").strip()
    if configured and not _same_bot(username, configured):
        logger.error(
            "[CONFIG] Токен принадлежит @%s, а в VITE_BOT_USERNAME указан @%s. Подпись данных входа "
            "делается токеном бота, из которого открыто приложение, поэтому у всех пользователей вход "
            "будет отклонён (Invalid hash). Исправьте TELEGRAM_BOT_TOKEN или VITE_BOT_USERNAME в .env",
            username, configured.lstrip("@"),
        )
    return username
