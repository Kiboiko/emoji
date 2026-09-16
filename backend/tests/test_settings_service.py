"""
Настройки: валидация значений и поведение кеша.

Кеш здесь не оптимизация ради оптимизации, а место, где настройка может
«залипнуть»: она читается на каждой оплате, и устаревшее значение означает
неверную комиссию, посчитанную молча.
"""

import pytest

from models.app_setting import AppSetting
from services import settings_service as st

pytestmark = pytest.mark.asyncio


async def test_defaults_used_when_db_empty(db):
    """Отсутствие строки в БД — не ошибка, берётся дефолт из кода."""
    assert await st.get_int(db, "referral_l1_bp") == 300


async def test_set_and_read_back(db):
    await st.set_setting(db, "referral_l1_bp", 750)
    assert await st.get_int(db, "referral_l1_bp") == 750


async def test_bounds_are_enforced(db):
    """Из админки нельзя выставить комиссию 300%."""
    with pytest.raises(st.SettingValidationError):
        await st.set_setting(db, "referral_l1_bp", 50_000)

    with pytest.raises(st.SettingValidationError):
        await st.set_setting(db, "referral_l1_bp", -1)


async def test_unknown_key_rejected(db):
    with pytest.raises(st.UnknownSettingKey):
        await st.get(db, "no_such_setting")

    with pytest.raises(st.UnknownSettingKey):
        await st.set_setting(db, "no_such_setting", 1)


async def test_write_invalidates_cache(db):
    """Своя же запись должна быть видна немедленно, без ожидания TTL."""
    await st.get_int(db, "referral_l1_bp")          # прогреваем кеш
    await st.set_setting(db, "referral_l1_bp", 900)

    assert await st.get_int(db, "referral_l1_bp") == 900


async def test_cache_expires(db, monkeypatch):
    """
    Значение, изменённое мимо этого процесса, подхватывается по истечении TTL.

    Так ведёт себя правка из соседнего воркера uvicorn: set_setting() сбрасывает
    кеш только там, где выполнился, и без срока жизни этот процесс считал бы по
    старому значению до перезапуска.
    """
    await st.set_setting(db, "referral_l1_bp", 300)
    assert await st.get_int(db, "referral_l1_bp") == 300

    # Пишем напрямую в БД, минуя set_setting: кеш процесса не сбрасывается
    row = await db.get(AppSetting, "referral_l1_bp")
    row.value = {"v": 1234}
    await db.flush()

    # Кеш ещё свежий — видно старое значение
    assert await st.get_int(db, "referral_l1_bp") == 300

    # Сдвигаем часы за пределы TTL
    real_monotonic = st.time.monotonic
    monkeypatch.setattr(
        st.time, "monotonic",
        lambda: real_monotonic() + st.CACHE_TTL_SECONDS + 1,
    )

    assert await st.get_int(db, "referral_l1_bp") == 1234
