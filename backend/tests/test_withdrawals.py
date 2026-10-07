"""
Выводы средств: две валюты.

Реферальный баланс номинирован в USD, заработок продавца — в TON. До
появления валюты выводить можно было только USD, и заработанные продавцами
TON оставались на внутреннем счёте навсегда.
"""

import base64
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
from services import settings_service, ton_address, ton_service, withdrawal_service
from services.money import to_minor

pytestmark = pytest.mark.asyncio

NOTIFY = "services.telegram_service.telegram_service"


def _wallet(seed: int = 1) -> str:
    """Настоящий по формату адрес TON (UQ…) — сервер проверяет контрольную сумму."""
    body = bytes([ton_address.NON_BOUNCEABLE, 0]) + bytes([seed]) * 32
    crc = ton_address._crc16(body).to_bytes(2, "big")
    return base64.urlsafe_b64encode(body + crc).decode()


WALLET = _wallet()


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


async def _request(db, user, amount, wallet=WALLET, currency=None):
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
    await settings_service.set_setting(db, "payout_min_ton_nano", 0)

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


# ---------------------------------------------------------------------------
# Проверки заявки
# ---------------------------------------------------------------------------

async def test_mistyped_ton_address_is_refused(db, funded):
    """Опечатка в адресе — деньги в никуда: заявка не принимается вовсе."""
    seller = await funded(ton="5", username="typo_seller")
    broken = WALLET[:-3] + ("AAA" if not WALLET.endswith("AAA") else "BBB")

    with pytest.raises(HTTPException) as exc:
        await _request(db, seller, "2", wallet=broken, currency="TON")
    assert exc.value.status_code == 400
    assert (await fin.user_account(db, seller.id, "TON")).hold_minor == 0


async def test_minimum_withdrawal_comes_from_settings(db, funded):
    seller = await funded(ton="5", username="small_seller")
    await settings_service.set_setting(db, "payout_min_ton_nano", 2_000_000_000)

    with pytest.raises(HTTPException) as exc:
        await _request(db, seller, "1.5", currency="TON")
    assert "Минимальная сумма вывода — 2 TON" in exc.value.detail

    await _request(db, seller, "2", currency="TON")


async def test_address_parser_knows_both_forms():
    parsed = ton_address.parse(WALLET)
    assert parsed.workchain == 0 and parsed.bounceable is False
    assert ton_address.same(WALLET, parsed.raw)
    assert not ton_address.is_valid("UQTargetWallet123456")


# ---------------------------------------------------------------------------
# Выплата через кошелёк площадки
# ---------------------------------------------------------------------------

@pytest.fixture
async def admin(user_factory):
    return await user_factory(username="payout_admin_2", is_admin=True)


async def _pending(db, funded, amount="3", username="tc_seller"):
    seller = await funded(ton="5", username=username)
    created = await _request(db, seller, amount, currency="TON")
    return seller, created


def _transfer(comment: str, nano: int) -> ton_service.OutTransfer:
    return ton_service.OutTransfer(
        tx_hash="abc123", utime=0, destination=WALLET, value_nano=nano, comment=comment,
    )


async def test_payout_found_on_chain_closes_request(db, funded, admin):
    seller, created = await _pending(db, funded)

    prepared = await wd.prepare_payout(created.id, admin=admin, db=db)
    assert prepared["address"] == WALLET
    assert prepared["amount_nano"] == str(3 * 10**9)
    comment = prepared["comment"]

    found = AsyncMock(return_value=[_transfer(comment, 3 * 10**9)])
    with patch.object(ton_service, "fetch_outgoing_transfers", found), \
         patch(f"{NOTIFY}.send_message", new=AsyncMock()) as told:
        result = await wd.payout_sent(created.id, admin=admin, db=db)

    assert result.status == WithdrawalStatus.COMPLETED
    assert result.tx_hash == "abc123"
    account = await fin.user_account(db, seller.id, "TON")
    assert account.balance_minor == 2 * 10**9      # 5 − 3 выплачено
    assert account.hold_minor == 0
    assert "Средства выведены: 3 TON" in told.await_args.args[1]


async def test_payout_waits_until_transfer_appears(db, funded, admin):
    _, created = await _pending(db, funded, username="tc_wait")
    await wd.prepare_payout(created.id, admin=admin, db=db)

    with patch.object(ton_service, "fetch_outgoing_transfers", AsyncMock(return_value=[])):
        result = await wd.payout_sent(created.id, admin=admin, db=db)

    assert result.status == WithdrawalStatus.SENDING


async def test_smaller_transfer_does_not_close_request(db, funded, admin):
    _, created = await _pending(db, funded, username="tc_short")
    prepared = await wd.prepare_payout(created.id, admin=admin, db=db)

    short = AsyncMock(return_value=[_transfer(prepared["comment"], 10**9)])
    with patch.object(ton_service, "fetch_outgoing_transfers", short):
        result = await wd.payout_sent(created.id, admin=admin, db=db)

    assert result.status == WithdrawalStatus.SENDING


async def test_late_transfer_after_revert_is_not_paid_twice(db, funded, admin):
    """
    Админ решил, что перевод не прошёл, и вернул заявку в ожидание, а перевод
    всё-таки дошёл. Заявка закрывается сама и второй выплаты не ждёт.
    """
    seller, created = await _pending(db, funded, username="tc_late")
    prepared = await wd.prepare_payout(created.id, admin=admin, db=db)
    with patch.object(ton_service, "fetch_outgoing_transfers", AsyncMock(return_value=[])):
        await wd.payout_sent(created.id, admin=admin, db=db)
    await wd.update_withdrawal_status(
        created.id, WithdrawalUpdate(status=WithdrawalStatus.PENDING), admin=admin, db=db,
    )

    late = AsyncMock(return_value=[_transfer(prepared["comment"], 3 * 10**9)])
    with patch.object(ton_service, "fetch_outgoing_transfers", late), \
         patch(f"{NOTIFY}.send_message", new=AsyncMock()):
        closed = await withdrawal_service.confirm_sent_payouts(db)

    assert closed == 1
    row = await db.get(Withdrawal, created.id)
    assert row.status == WithdrawalStatus.COMPLETED


async def test_rejection_returns_money_to_balance(db, funded, admin):
    seller, created = await _pending(db, funded, username="tc_reject")

    with patch(f"{NOTIFY}.send_message", new=AsyncMock()) as told:
        result = await wd.reject_withdrawal(
            created.id, wd.RejectIn(reason="Кошелёк в чёрном списке"), admin=admin, db=db,
        )

    assert result.status == WithdrawalStatus.REJECTED
    account = await fin.user_account(db, seller.id, "TON")
    assert account.balance_minor == 5 * 10**9
    assert account.hold_minor == 0
    assert "отклонена: Кошелёк в чёрном списке" in told.await_args.args[1]
    assert (await fin.reconcile(db)).ok


async def test_sent_payout_cannot_be_rejected(db, funded, admin):
    """Перевод мог уже уйти — сначала «не прошёл», потом отказ."""
    _, created = await _pending(db, funded, username="tc_sent_reject")
    await wd.prepare_payout(created.id, admin=admin, db=db)
    with patch.object(ton_service, "fetch_outgoing_transfers", AsyncMock(return_value=[])):
        await wd.payout_sent(created.id, admin=admin, db=db)

    with pytest.raises(HTTPException):
        await wd.reject_withdrawal(created.id, wd.RejectIn(reason="Передумал"), admin=admin, db=db)


async def test_summary_shows_what_belongs_to_platform(db, funded, admin):
    """Свободно = на кошельке − деньги пользователей − замороженное в сделках."""
    await funded(ton="5", username="tc_summary")      # пользователю площадка должна 5 TON

    with patch.object(ton_service, "fetch_wallet_balance", AsyncMock(return_value=12 * 10**9)):
        summary = await wd.payouts_summary(admin=admin, db=db)

    assert summary["wallet_nano"] == str(12 * 10**9)
    assert summary["users_nano"] == str(5 * 10**9)
    assert summary["free_nano"] == str(7 * 10**9)
