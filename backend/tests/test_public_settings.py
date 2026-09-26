"""
Комиссии, видимые снаружи.

Продавец должен знать, сколько удержит площадка, до того как назначит цену.
Раньше процент жил только в админке и в расчётах на сервере.
"""

import pytest

from routes import settings as settings_routes
from services import settings_service

pytestmark = pytest.mark.asyncio


async def test_public_settings_return_commissions(db):
    data = await settings_routes.public_settings(db=db)

    assert data["commission_p2p_bp"] == 200
    assert data["commission_subscription_bp"] == 200


async def test_public_settings_follow_admin_changes(db):
    await settings_service.set_setting(db, "commission_p2p_bp", 350)
    await db.commit()

    data = await settings_routes.public_settings(db=db)
    assert data["commission_p2p_bp"] == 350


async def test_public_settings_expose_nothing_else(db):
    """
    Белый список, а не «весь набор настроек минус пара ключей». Иначе новая
    настройка попадает наружу сама собой, и заметить это некому.
    """
    data = await settings_routes.public_settings(db=db)

    assert set(data) == {"commission_p2p_bp", "commission_subscription_bp"}
