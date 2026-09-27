"""
Настройки площадки, которые видны снаружи.

Пока здесь только комиссии. Продавец должен знать, сколько площадка
удержит, до того как назначит цену, а не после первой продажи — раньше
этот процент жил только в админке и в расчётах на сервере.

Наружу уходит именно белый список ключей, а не весь набор настроек:
сроки, лимиты и адреса кошельков никому за пределами админки не нужны.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services import settings_service

router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get("/public")
async def public_settings(db: AsyncSession = Depends(get_db)):
    """
    Комиссии площадки в базисных пунктах (200 = 2%).

    Публичный: цену продавец назначает до того, как где-либо авторизуется
    как продавец, а покупателю процент показывают на странице подписки.
    """
    return {
        "commission_p2p_bp": await settings_service.get_int(db, "commission_p2p_bp"),
        "commission_subscription_bp": await settings_service.get_int(
            db, "commission_subscription_bp"
        ),
        # Контакт поддержки: кнопка в приложении должна вести в живой чат, а
        # адрес этого чата меняется без выкладки
        "support_contact": (await settings_service.get_str(db, "support_contact")).strip(),
    }
