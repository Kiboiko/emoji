"""
Настройки приложения, редактируемые через админку.

Как это работает:
  * все известные ключи описаны в SETTING_DEFS ниже — это единственное место,
    где заводится новая настройка (тип, дефолт, описание);
  * значение берётся из таблицы app_settings, при отсутствии — из дефолта.
    Поэтому добавление ключа не требует миграции данных;
  * значения кешируются в памяти процесса: сбрасываются при записи и в любом
    случае перечитываются раз в CACHE_TTL_SECONDS, чтобы правка из админки
    доходила до всех процессов без перезапуска.

Проценты хранятся в базисных пунктах (bp): 2% = 200. См. services/money.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.app_setting import AppSetting

logger = logging.getLogger(__name__)

SettingType = Literal["int", "bool", "str", "list"]


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: SettingType
    default: Any
    description: str
    #  Границы для числовых настроек — чтобы из админки нельзя было
    #  выставить комиссию 300% или отрицательный срок
    min_value: int | None = None
    max_value: int | None = None


SETTING_DEFS: tuple[SettingDef, ...] = (
    # --- Комиссии ---------------------------------------------------------
    SettingDef("commission_p2p_bp", "int", 200,
               "Комиссия платформы с P2P-сделки, базисные пункты (200 = 2%)",
               0, 10_000),
    SettingDef("commission_subscription_bp", "int", 200,
               "Комиссия платформы с подписки, базисные пункты",
               0, 10_000),

    # --- Реферальная программа -------------------------------------------
    SettingDef("referral_l1_bp", "int", 300,
               "Реферальные 1-го уровня, базисные пункты (300 = 3%)",
               0, 10_000),
    SettingDef("referral_l2_bp", "int", 0,
               "Реферальные 2-го уровня. 0 — второй уровень выключен",
               0, 10_000),
    SettingDef("referral_applies_to", "list", ["product", "subscription", "p2p"],
               "На какие типы покупок начисляются реферальные"),

    # --- Оплата -----------------------------------------------------------
    SettingDef("ton_rate_source", "str", "coingecko",
               "Источник курса USD/TON: coingecko | fixed. "
               "fixed берёт значение из ton_rate_fixed_usd — нужен для тестов "
               "и как аварийный вариант, если внешний источник недоступен"),
    SettingDef("ton_rate_fixed_usd", "str", "3.00",
               "Курс TON в USD при ton_rate_source=fixed. Строка, а не число: "
               "в деньгах используется Decimal, float запрещён"),
    SettingDef("ton_rate_ttl_sec", "int", 900,
               "Сколько секунд действует зафиксированный для заказа курс USD/TON",
               60, 86_400),
    SettingDef("ton_min_confirm_sec", "int", 0,
               "Сколько секунд ждать после появления транзакции в индексере "
               "перед выдачей товара. 0 — выдавать сразу"),
    SettingDef("order_payment_ttl_min", "int", 30,
               "Сколько минут ждём оплату заказа, после чего он отменяется",
               5, 1_440),

    # --- P2P --------------------------------------------------------------
    SettingDef("p2p_max_pending_listings", "int", 5,
               "Сколько заявок на размещение может висеть на модерации у одного продавца",
               1, 100),
    SettingDef("p2p_reject_block_threshold", "int", 3,
               "Сколько отказов подряд ограничивают продавца",
               1, 100),
    SettingDef("p2p_confirm_deadline_days", "int", 7,
               "Через сколько дней получение товара подтверждается автоматически",
               1, 90),
    SettingDef("chat_retention_days", "int", 7,
               "Сколько дней после завершения сделки стороны могут читать переписку. "
               "Потом она пропадает у них из приложения; в админке остаётся",
               1, 365),

    # --- Выплаты ----------------------------------------------------------
    SettingDef("payout_min_ton_nano", "int", 1_000_000_000,
               "Минимальная сумма заявки на вывод в нанотонах (1e9 = 1 TON)",
               0, None),

    # --- Поддержка --------------------------------------------------------
    SettingDef("support_contact", "str", "",
               "Куда писать в поддержку: @username или ссылка. Пока пусто, "
               "кнопка в приложении ведёт в чат с ботом"),

    # --- Условия площадки -------------------------------------------------
    SettingDef("terms_version", "str", "1.0",
               "Текущая версия условий использования площадки. При изменении "
               "текста повышайте версию — пользователи примут условия заново"),
    SettingDef("terms_text", "str", "",
               "Текст условий использования площадки (Markdown). Пишет владелец "
               "площадки — пока пусто, страница показывает предупреждение"),
)

_DEFS_BY_KEY: dict[str, SettingDef] = {d.key: d for d in SETTING_DEFS}

# Кеш процесса: ключ -> значение. Сбрасывается при записи через set_setting().
_cache: dict[str, Any] | None = None
_cache_loaded_at: float = 0.0

# Кеш живёт ограниченное время, а не до записи.
#
# set_setting() сбрасывает кеш только в СВОЁМ процессе. Пока uvicorn запущен с
# одним воркером, этого достаточно, но `--workers 4` в проде — обычное дело, и
# тогда правка комиссии в админке применилась бы лишь в одном процессе из
# четырёх, а остальные продолжили бы считать по-старому до перезапуска.
# Незаметно и прямо в деньгах. Срок жизни ограничивает такое расхождение
# несколькими секундами и не требует ни общего кеша, ни сигналов между
# процессами.
CACHE_TTL_SECONDS = 30.0


class UnknownSettingKey(KeyError):
    pass


class SettingValidationError(ValueError):
    pass


def _coerce(defn: SettingDef, raw: Any) -> Any:
    """Приводит значение к объявленному типу и проверяет границы."""
    if defn.type == "int":
        if isinstance(raw, bool) or not isinstance(raw, int):
            try:
                raw = int(raw)
            except (TypeError, ValueError):
                raise SettingValidationError(f"{defn.key}: ожидается целое число, получено {raw!r}")
        if defn.min_value is not None and raw < defn.min_value:
            raise SettingValidationError(f"{defn.key}: минимум {defn.min_value}, получено {raw}")
        if defn.max_value is not None and raw > defn.max_value:
            raise SettingValidationError(f"{defn.key}: максимум {defn.max_value}, получено {raw}")
        return raw
    if defn.type == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)
    if defn.type == "list":
        if not isinstance(raw, list):
            raise SettingValidationError(f"{defn.key}: ожидается список, получено {type(raw).__name__}")
        return raw
    return str(raw)


async def load_cache(db: AsyncSession) -> dict[str, Any]:
    """Читает все настройки из БД, накладывая их поверх дефолтов."""
    global _cache, _cache_loaded_at

    values: dict[str, Any] = {d.key: d.default for d in SETTING_DEFS}

    rows = (await db.execute(select(AppSetting))).scalars().all()
    for row in rows:
        defn = _DEFS_BY_KEY.get(row.key)
        if defn is None:
            # Ключ есть в БД, но не описан в коде — вероятно, остался от
            # удалённой функциональности. Не падаем, но и не используем.
            logger.warning("[SETTINGS] Неизвестный ключ в app_settings: %s", row.key)
            continue
        try:
            values[row.key] = _coerce(defn, row.value.get("v") if isinstance(row.value, dict) else row.value)
        except SettingValidationError as e:
            logger.error("[SETTINGS] Некорректное значение в БД, берём дефолт: %s", e)

    _cache = values
    _cache_loaded_at = time.monotonic()
    return values


def invalidate_cache() -> None:
    global _cache, _cache_loaded_at
    _cache = None
    _cache_loaded_at = 0.0


def _cache_is_fresh() -> bool:
    # monotonic, а не time(): перевод системных часов не должен ни продлевать
    # кеш навсегда, ни сбрасывать его на каждом обращении
    return _cache is not None and (time.monotonic() - _cache_loaded_at) < CACHE_TTL_SECONDS


async def get_all(db: AsyncSession) -> dict[str, Any]:
    if not _cache_is_fresh():
        return await load_cache(db)
    return dict(_cache)  # type: ignore[arg-type]


async def get(db: AsyncSession, key: str) -> Any:
    if key not in _DEFS_BY_KEY:
        raise UnknownSettingKey(key)
    if not _cache_is_fresh():
        await load_cache(db)
    return _cache[key]  # type: ignore[index]


async def get_int(db: AsyncSession, key: str) -> int:
    return int(await get(db, key))


async def get_list(db: AsyncSession, key: str) -> list:
    return list(await get(db, key))


async def get_str(db: AsyncSession, key: str) -> str:
    return str(await get(db, key))


async def set_setting(
    db: AsyncSession,
    key: str,
    value: Any,
    *,
    admin_id=None,
) -> Any:
    """
    Записывает настройку. Значение валидируется по объявленному типу и границам,
    чтобы из админки нельзя было выставить комиссию 300%.
    """
    defn = _DEFS_BY_KEY.get(key)
    if defn is None:
        raise UnknownSettingKey(key)

    coerced = _coerce(defn, value)

    stmt = pg_insert(AppSetting).values(
        key=key,
        value={"v": coerced},
        description=defn.description,
        updated_by_admin_id=admin_id,
    ).on_conflict_do_update(
        index_elements=[AppSetting.key],
        set_={"value": {"v": coerced}, "updated_by_admin_id": admin_id},
    )
    await db.execute(stmt)
    await db.commit()

    invalidate_cache()
    logger.info("[SETTINGS] %s = %r (админ %s)", key, coerced, admin_id)
    return coerced


def describe() -> list[dict[str, Any]]:
    """Метаданные всех настроек — для формы в админке."""
    return [
        {
            "key": d.key,
            "type": d.type,
            "default": d.default,
            "description": d.description,
            "min": d.min_value,
            "max": d.max_value,
        }
        for d in SETTING_DEFS
    ]
