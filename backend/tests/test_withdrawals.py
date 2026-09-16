"""
Выводы средств: две валюты.

Реферальный баланс номинирован в USD, заработок продавца — в TON. До
появления валюты выводить можно было только USD, и заработанные продавцами
TON оставались на внутреннем счёте навсегда.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from models.withdrawal import Withdrawal, WithdrawalStatus
from routes import withdrawals as wd
from schemas.withdrawal import WithdrawalCreate, WithdrawalUpdate
from services import finance_service as fin
from services.money import to_minor

pytestmark = pytest.mark.asyncio

NOTIFY = "services.telegram_service.telegram_service"


@pytest.fixture
async def funded(db, user_factory):
    """Пользователь с балансом в обеих валютах."""
    async def make(usd="0", ton="0", **kwargs):
        user = await user_factory(**kwargs)
        for currency, amount in (("USD", usd), ("TON", ton)):
            if Decimal(amount) <= 0:
                continue
            account = await fin.user_account(db, user.id, currency)
            await fin.deposit_from_external(
                db, account=account,
                amount_minor=to_minor(Decimal(amount), currency),
                ref_type=fin.LedgerRefType.ORDER, ref_id=uuid.uuid4(),
            )
        await db.flush()
        return user
    return make


async def _request(db, user, amount, wallet="UQTargetWallet123456", currency=None):
    with patch(f"{NOTIFY}.send_withdrawal_request_notification", new=AsyncMock()):
        return await wd.request_withdrawal(
            WithdrawalCreate(amount=Decimal(amount), wallet=wallet, currency=currency),
            user=user, db=db,
        )


async def _complete(db, admin, withdrawal_id):
    with patch(f"{NOTIFY}.send_message", new=AsyncMock()):
        return await wd.update_withdrawal_status(
            withdrawal_id, WithdrawalUpdate(status=WithdrawalStatus.COMPLETED),
            admin=admin, db=db,
        )


async def test_ton_withdrawal_requested(db, funded):
    """Продавец может вывести заработанные TON."""
    seller = await funded(ton="24.5", username="ton_seller")

    result = await _request(db, seller, "24.5", currency="TON")

    assert result.currency == "TON"
    account = await fin.user_account(db, seller.id, "TON")
    # Деньги заморожены, а не списаны: перевод делает администрация
    assert account.balance_minor == to_minor(Decimal("24.5"), "TON")
    assert account.hold_minor == to_minor(Decimal("24.5"), "TON")
    assert account.available_minor == 0


async def test_ton_amount_keeps_precision(db, funded):
    """
    Дробные TON не должны теряться.

    У TON девять знаков после запятой. Со схемой на два знака вывести можно
    было бы только круглые суммы, а остаток застрял бы на счёте навсегда.
    """
    seller = await funded(ton="0.123456789", username="precise_seller")

    await _request(db, seller, "0.123456789", currency="TON")

    row = (await db.execute(select(Withdrawal))).scalars().one()
    assert row.amount_minor == 123_456_789


async def test_usd_withdrawal_still_default(db, funded):
    """Вызов без валюты работает как раньше — это витрина с реф.балансом."""
    user = await funded(usd="10.00", username="usd_user")

    result = await _request(db, user, "10.00")

    assert result.currency == "USD"
    account = await fin.user_account(db, user.id, "USD")
    assert account.hold_minor == 1000


async def test_currencies_do_not_mix(db, funded):
    """
    Баланс в TON не позволяет вывести USD.

    Без проверки по счёту нужной валюты продавец с 24 TON вывел бы 24 доллара.
    """
    seller = await funded(ton="24.5", usd="0", username="mixed_seller")

    with pytest.raises(HTTPException) as exc:
        await _request(db, seller, "24.5", currency="USD")

    assert exc.value.status_code == 400
    assert "Недостаточно" in exc.value.detail


async def test_cannot_withdraw_more_than_available(db, funded):
    seller = await funded(ton="1.0", username="greedy_seller")
    await _request(db, seller, "1.0", currency="TON")

    # Первая заявка заморозила весь баланс — вторая не должна пройти
    with pytest.raises(HTTPException) as exc:
        await _request(db, seller, "1.0", currency="TON")
    assert exc.value.status_code == 400


async def test_unknown_currency_refused(db, funded):
    user = await funded(usd="10.00", username="weird_currency")

    with pytest.raises(HTTPException) as exc:
        await _request(db, user, "1.00", currency="BTC")
    assert exc.value.status_code == 400


async def test_completion_moves_ton_out(db, funded, user_factory):
    """Подтверждение админом списывает деньги со счёта и снимает заморозку."""
    admin = await user_factory(username="payout_admin", is_admin=True)
    seller = await funded(ton="5.0", username="paid_seller")
    created = await _request(db, seller, "5.0", currency="TON")

    await _complete(db, admin, created.id)

    account = await fin.user_account(db, seller.id, "TON")
    assert account.balance_minor == 0
    assert account.hold_minor == 0


async def test_referral_cache_untouched_by_ton(db, funded):
    """
    Вывод TON не должен трогать кеш реферального баланса.

    referral_earnings показывается на витрине в долларах; запись туда суммы в
    TON сложила бы в одном поле две разные валюты.
    """
    seller = await funded(ton="5.0", usd="7.00", username="cache_seller")
    before = seller.referral_earnings

    await _request(db, seller, "5.0", currency="TON")

    await db.refresh(seller)
    assert seller.referral_earnings == before


async def test_referral_cache_follows_usd(db, funded):
    user = await funded(usd="10.00", username="cache_usd_user")

    await _request(db, user, "4.00")

    await db.refresh(user)
    # Заявка сразу уменьшает показываемый баланс: 10 - 4 заморожено
    assert user.referral_earnings == 6.0
