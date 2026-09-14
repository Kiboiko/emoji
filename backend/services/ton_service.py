"""
Приём оплаты в TON через TON Connect.

Схема работы принципиально отличается от CryptoBot: у блокчейна нет вебхука
«вам заплатили». Поэтому:

  1. выставляем счёт — фиксируем курс, считаем сумму в нанотонах и выдаём
     УНИКАЛЬНЫЙ текстовый комментарий;
  2. фронт передаёт кошельку транзакцию (адрес + сумма + комментарий),
     пользователь подписывает её сам;
  3. бэкенд опрашивает индексер и ищет входящую транзакцию с нашим
     комментарием и суммой не меньше ожидаемой.

Ключевое правило: факт оплаты устанавливается ТОЛЬКО по данным блокчейна.
Фронт может прислать хеш как подсказку для ускорения проверки, но никогда не
как доказательство — иначе оплату можно подделать одним запросом.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_UP

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from services import settings_service
from services.money import to_minor

logger = logging.getLogger(__name__)

CURRENCY = "TON"
NANO = 1_000_000_000

# Кеш курса в памяти процесса: (курс, момент получения)
_rate_cache: tuple[Decimal, float] | None = None


class TonError(Exception):
    pass


class TonNotConfigured(TonError):
    pass


class RateUnavailable(TonError):
    pass


# ---------------------------------------------------------------------------
# Курс USD -> TON
# ---------------------------------------------------------------------------

async def _fetch_rate_coingecko() -> Decimal:
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=the-open-network&vs_currencies=usd"
    )
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    try:
        # str(), а не float напрямую: json уже отдал float, но в Decimal его
        # нужно заводить через строку, иначе тащим двоичную погрешность
        return Decimal(str(data["the-open-network"]["usd"]))
    except (KeyError, TypeError) as e:
        raise RateUnavailable(f"Неожиданный ответ CoinGecko: {data!r}") from e


async def get_rate(db: AsyncSession, *, force: bool = False) -> Decimal:
    """
    Курс: сколько USD стоит 1 TON.

    Кешируется на ton_rate_ttl_sec. Источник настраивается в админке:
    coingecko или fixed (для тестов и как аварийный вариант, если внешний
    источник лежит).
    """
    global _rate_cache

    source = await settings_service.get_str(db, "ton_rate_source")

    if source == "fixed":
        return Decimal(await settings_service.get_str(db, "ton_rate_fixed_usd"))

    ttl = await settings_service.get_int(db, "ton_rate_ttl_sec")
    if not force and _rate_cache is not None:
        rate, fetched_at = _rate_cache
        if time.monotonic() - fetched_at < ttl:
            return rate

    try:
        rate = await _fetch_rate_coingecko()
    except Exception as e:
        # Отдавать заказ по устаревшему курсу лучше, чем не отдавать вовсе,
        # но только если он вообще был получен когда-то в этом процессе.
        if _rate_cache is not None:
            logger.warning("[TON] Курс недоступен (%s), берём устаревший из кеша", e)
            return _rate_cache[0]
        raise RateUnavailable(f"Не удалось получить курс TON: {e}") from e

    if rate <= 0:
        raise RateUnavailable(f"Некорректный курс TON: {rate}")

    _rate_cache = (rate, time.monotonic())
    logger.info("[TON] Курс обновлён: 1 TON = %s USD", rate)
    return rate


def reset_rate_cache() -> None:
    """Нужен тестам и ручному сбросу после смены источника."""
    global _rate_cache
    _rate_cache = None


def usd_to_nano(usd_amount: Decimal, rate_usd_per_ton: Decimal) -> int:
    """
    USD -> нанотоны по заданному курсу.

    Округление ВВЕРХ: при округлении вниз пользователь заплатил бы на
    несколько нанотон меньше ожидаемого, и платёж попал бы в underpaid.
    """
    if rate_usd_per_ton <= 0:
        raise RateUnavailable("Курс должен быть положительным")
    tons = Decimal(usd_amount) / rate_usd_per_ton
    return int((tons * NANO).to_integral_value(rounding=ROUND_UP))


# ---------------------------------------------------------------------------
# Выставление счёта
# ---------------------------------------------------------------------------

def generate_payment_comment() -> str:
    """
    Уникальный комментарий платежа.

    Не используем order_id: UUID в комментарии длинный и раскрывает
    внутренние идентификаторы всем, кто смотрит блокчейн. Короткий случайный
    код и читается человеком, и не течёт наружу.
    """
    return f"MP-{secrets.token_hex(6).upper()}"


def require_receiving_address() -> str:
    address = settings.TON_RECEIVING_ADDRESS.strip()
    if not address:
        raise TonNotConfigured(
            "TON_RECEIVING_ADDRESS не задан — приём оплаты невозможен. "
            "Укажите адрес кошелька платформы в .env"
        )
    return address


@dataclass
class TransactionRequest:
    """То, что фронт передаёт кошельку через TON Connect."""
    address: str
    amount_nano: int
    comment: str
    valid_until: int          # unix-время, после которого кошелёк не подпишет
    network: str
    rate_usd_per_ton: str
    usd_amount: str

    def as_dict(self) -> dict:
        return {
            "address": self.address,
            "amount_nano": str(self.amount_nano),
            "amount_ton": str(Decimal(self.amount_nano) / NANO),
            "comment": self.comment,
            "valid_until": self.valid_until,
            "network": self.network,
            "rate_usd_per_ton": self.rate_usd_per_ton,
            "usd_amount": self.usd_amount,
        }


# ---------------------------------------------------------------------------
# Проверка транзакции в блокчейне
# ---------------------------------------------------------------------------

@dataclass
class OnChainTx:
    tx_hash: str
    lt: int
    utime: int
    source: str | None
    value_nano: int
    comment: str


async def fetch_incoming_transactions(limit: int | None = None) -> list[OnChainTx]:
    """
    Забирает последние входящие транзакции кошелька платформы.

    Используется toncenter v2 getTransactions: он отдаёт текстовый комментарий
    простого перевода прямо в in_msg.message, чего достаточно для
    сопоставления и не требует разбора ячеек.
    """
    address = require_receiving_address()
    # Параметр archival сюда НЕ передаём: toncenter отвечает 500 на
    # `archival=false`, хотя тот же запрос без него отрабатывает нормально.
    # Поведение по умолчанию (нежёсткий узел) нас устраивает — нужны свежие
    # транзакции, а не глубокая история.
    params = {
        "address": address,
        "limit": limit or settings.TON_TX_FETCH_LIMIT,
    }
    if settings.TON_API_KEY:
        params["api_key"] = settings.TON_API_KEY

    url = f"{settings.ton_api_base}/getTransactions"

    # Любая проблема с индексером должна выглядеть как TonError, а не утекать
    # наружу httpx-исключением: вызывающий код отличает «индексер недоступен»
    # (отдать 503 и попробовать позже) от «оплаты не было» (обычный ответ).
    # Иначе временная недоступность индексера превращается в 500 у клиента и,
    # что хуже, может быть истолкована как «не оплачено».
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as e:
        raise TonError(
            f"Индексер ответил {e.response.status_code} для адреса {address}"
        ) from e
    except httpx.HTTPError as e:
        raise TonError(f"Индексер недоступен: {e}") from e
    except ValueError as e:  # некорректный JSON
        raise TonError(f"Индексер вернул не-JSON: {e}") from e

    if not payload.get("ok"):
        raise TonError(f"Индексер вернул ошибку: {payload.get('error')!r}")

    result: list[OnChainTx] = []
    for tx in payload.get("result", []):
        in_msg = tx.get("in_msg") or {}
        # Пустой source — служебная транзакция самого кошелька, не платёж
        if not in_msg.get("source"):
            continue
        try:
            value = int(in_msg.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue

        result.append(OnChainTx(
            tx_hash=tx.get("transaction_id", {}).get("hash", ""),
            lt=int(tx.get("transaction_id", {}).get("lt") or 0),
            utime=int(tx.get("utime") or 0),
            source=in_msg.get("source"),
            value_nano=value,
            comment=(in_msg.get("message") or "").strip(),
        ))

    return result


@dataclass
class MatchResult:
    matched: bool
    tx: OnChainTx | None = None
    underpaid: bool = False


def match_payment(
    txs: list[OnChainTx],
    *,
    comment: str,
    expected_nano: int,
    window_start: datetime,
    window_end: datetime,
) -> MatchResult:
    """
    Ищет транзакцию, оплачивающую конкретный счёт.

    Сопоставление по комментарию, а не по сумме и отправителю: суммы
    повторяются, а адрес отправителя заранее неизвестен.

    Временнóе окно отсекает случайное совпадение со старым платежом, если
    комментарий когда-то переиспользуется.
    """
    start_ts = int(window_start.timestamp())
    end_ts = int(window_end.timestamp())

    best: OnChainTx | None = None
    underpaid_candidate: OnChainTx | None = None

    for tx in txs:
        if tx.comment != comment:
            continue
        if not (start_ts <= tx.utime <= end_ts):
            logger.warning(
                "[TON] Транзакция %s с нашим комментарием вне окна (utime=%s)",
                tx.tx_hash, tx.utime,
            )
            continue
        if tx.value_nano >= expected_nano:
            # При нескольких подходящих берём самую раннюю
            if best is None or tx.lt < best.lt:
                best = tx
        else:
            if underpaid_candidate is None or tx.lt < underpaid_candidate.lt:
                underpaid_candidate = tx

    if best is not None:
        return MatchResult(matched=True, tx=best)
    if underpaid_candidate is not None:
        return MatchResult(matched=False, tx=underpaid_candidate, underpaid=True)
    return MatchResult(matched=False)


def payment_window(
    rate_locked_at: datetime, expires_at: datetime
) -> tuple[datetime, datetime]:
    """Окно поиска транзакции с запасом в обе стороны."""
    return (
        rate_locked_at - timedelta(seconds=settings.TON_LOOKBACK_SECONDS),
        expires_at + timedelta(seconds=settings.TON_LOOKAHEAD_SECONDS),
    )


def manifest_url() -> str:
    if settings.TONCONNECT_MANIFEST_URL:
        return settings.TONCONNECT_MANIFEST_URL
    return f"{settings.SITE_URL.rstrip('/')}/tonconnect-manifest.json"
