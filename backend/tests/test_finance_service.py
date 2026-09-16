"""
Финансовый слой: двойная запись, идемпотентность, заморозка, сверка.

Это самые важные тесты в проекте — здесь ошибка стоит реальных денег.
"""

import uuid

import pytest

from models.finance import AccountOwnerType, LedgerEntryType, LedgerRefType
from services import finance_service as fin
from services.finance_service import (
    InsufficientFunds, Posting, UnbalancedTransaction,
)
from services.money import split_by_bp, to_minor
from decimal import Decimal

pytestmark = pytest.mark.asyncio

TON = "TON"


class TestAccounts:
    async def test_creates_and_reuses(self, db, user_factory):
        user = await user_factory()
        a1 = await fin.user_account(db, user.id, TON)
        a2 = await fin.user_account(db, user.id, TON)
        assert a1.id == a2.id

    async def test_same_owner_different_currency_are_separate(self, db, user_factory):
        user = await user_factory()
        ton = await fin.user_account(db, user.id, TON)
        usd = await fin.user_account(db, user.id, "USD")
        assert ton.id != usd.id

    async def test_system_accounts_have_no_owner(self, db):
        platform = await fin.platform_account(db, TON)
        assert platform.owner_id is None
        assert platform.owner_type == AccountOwnerType.PLATFORM


class TestDoubleEntry:
    async def test_deposit_balances_to_zero(self, db, user_factory):
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)

        await fin.deposit_from_external(
            db, account=account, amount_minor=to_minor(Decimal("10"), TON),
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )

        external = await fin.external_account(db, TON)
        assert account.balance_minor == 10_000_000_000
        # Деньги не появились из воздуха: внешний счёт ушёл в минус ровно на ту же сумму
        assert external.balance_minor == -10_000_000_000

        report = await fin.reconcile(db)
        assert report.global_sum_by_currency[TON] == 0

    async def test_unbalanced_transaction_is_rejected(self, db, user_factory):
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)

        with pytest.raises(UnbalancedTransaction):
            await fin.post(
                db,
                ref_type=LedgerRefType.MANUAL, ref_id=uuid.uuid4(),
                postings=[Posting(
                    account=account, entry_type=LedgerEntryType.MANUAL_ADJUST,
                    amount_minor=1_000,
                )],
            )

    async def test_transfer_moves_money(self, db, user_factory):
        buyer, seller = await user_factory(), await user_factory()
        platform = await fin.platform_account(db, TON)
        seller_acc = await fin.user_account(db, seller.id, TON)

        await fin.deposit_from_external(
            db, account=platform, amount_minor=to_minor(Decimal("25"), TON),
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )
        await fin.transfer(
            db, src=platform, dst=seller_acc,
            amount_minor=to_minor(Decimal("24.5"), TON),
            entry_type=LedgerEntryType.SELLER_ACCRUAL,
            ref_type=LedgerRefType.DEAL, ref_id=uuid.uuid4(),
        )

        assert seller_acc.balance_minor == 24_500_000_000
        assert platform.balance_minor == 500_000_000  # комиссия осталась платформе

    async def test_cannot_spend_more_than_balance(self, db, user_factory):
        seller = await user_factory()
        platform = await fin.platform_account(db, TON)
        seller_acc = await fin.user_account(db, seller.id, TON)

        with pytest.raises(InsufficientFunds):
            await fin.transfer(
                db, src=platform, dst=seller_acc, amount_minor=1_000,
                entry_type=LedgerEntryType.SELLER_ACCRUAL,
                ref_type=LedgerRefType.DEAL, ref_id=uuid.uuid4(),
            )


class TestIdempotency:
    async def test_repeated_deposit_does_not_double(self, db, user_factory):
        """
        Сценарий из жизни: вебхук об оплате пришёл дважды (ретрай платёжки,
        параллельные воркеры). Второе начисление применяться не должно.
        """
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)
        order_id = uuid.uuid4()

        first = await fin.deposit_from_external(
            db, account=account, amount_minor=5_000_000_000,
            ref_type=LedgerRefType.ORDER, ref_id=order_id,
        )
        second = await fin.deposit_from_external(
            db, account=account, amount_minor=5_000_000_000,
            ref_type=LedgerRefType.ORDER, ref_id=order_id,
        )

        assert first.already_applied is False
        assert second.already_applied is True
        assert account.balance_minor == 5_000_000_000  # НЕ 10

    async def test_two_recipients_need_key_suffix(self, db, user_factory):
        """
        Два зачисления по одному основанию разным получателям.

        Проводка по внешнему счёту у них одинаковая, и без key_suffix ключ
        идемпотентности совпадает — вторая операция отбрасывается целиком как
        мнимый повтор, хотя получатель другой. Так терялось реферальное
        начисление второго уровня.
        """
        first_user = await user_factory(username="recipient_one")
        second_user = await user_factory(username="recipient_two")
        first_account = await fin.user_account(db, first_user.id, TON)
        second_account = await fin.user_account(db, second_user.id, TON)
        order_id = uuid.uuid4()

        await fin.deposit_from_external(
            db, account=first_account, amount_minor=3_000_000_000,
            ref_type=LedgerRefType.ORDER, ref_id=order_id,
            entry_type=LedgerEntryType.REFERRAL_ACCRUAL, key_suffix="l1",
        )
        result = await fin.deposit_from_external(
            db, account=second_account, amount_minor=1_000_000_000,
            ref_type=LedgerRefType.ORDER, ref_id=order_id,
            entry_type=LedgerEntryType.REFERRAL_ACCRUAL, key_suffix="l2",
        )

        assert result.already_applied is False
        assert first_account.balance_minor == 3_000_000_000
        assert second_account.balance_minor == 1_000_000_000

    async def test_same_suffix_still_deduplicates(self, db, user_factory):
        """key_suffix различает операции, но не отключает защиту от повтора."""
        user = await user_factory(username="suffix_repeat")
        account = await fin.user_account(db, user.id, TON)
        order_id = uuid.uuid4()

        for _ in range(2):
            await fin.deposit_from_external(
                db, account=account, amount_minor=2_000_000_000,
                ref_type=LedgerRefType.ORDER, ref_id=order_id,
                entry_type=LedgerEntryType.REFERRAL_ACCRUAL, key_suffix="l1",
            )

        assert account.balance_minor == 2_000_000_000

    async def test_different_refs_are_independent(self, db, user_factory):
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)

        for _ in range(3):
            await fin.deposit_from_external(
                db, account=account, amount_minor=1_000_000_000,
                ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
            )

        assert account.balance_minor == 3_000_000_000

    async def test_session_stays_usable_after_duplicate(self, db, user_factory):
        """
        После отката savepoint по дубликату сессия обязана остаться рабочей:
        иначе повторный вебхук ронял бы всю последующую обработку заказа.
        """
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)
        order_id = uuid.uuid4()

        await fin.deposit_from_external(
            db, account=account, amount_minor=1_000,
            ref_type=LedgerRefType.ORDER, ref_id=order_id,
        )
        await fin.deposit_from_external(
            db, account=account, amount_minor=1_000,
            ref_type=LedgerRefType.ORDER, ref_id=order_id,
        )
        # Сессия жива — следующая операция проходит
        await fin.deposit_from_external(
            db, account=account, amount_minor=2_000,
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )
        assert account.balance_minor == 3_000


class TestHold:
    async def test_hold_reduces_available_not_balance(self, db, user_factory):
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)
        await fin.deposit_from_external(
            db, account=account, amount_minor=10_000,
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )

        await fin.hold(
            db, account=account, amount_minor=4_000,
            entry_type=LedgerEntryType.WITHDRAWAL_RESERVE,
            ref_type=LedgerRefType.WITHDRAWAL, ref_id=uuid.uuid4(),
        )

        assert account.balance_minor == 10_000
        assert account.hold_minor == 4_000
        assert account.available_minor == 6_000

    async def test_cannot_hold_more_than_available(self, db, user_factory):
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)
        await fin.deposit_from_external(
            db, account=account, amount_minor=1_000,
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )

        with pytest.raises(InsufficientFunds):
            await fin.hold(
                db, account=account, amount_minor=1_001,
                entry_type=LedgerEntryType.ESCROW_HOLD,
                ref_type=LedgerRefType.DEAL, ref_id=uuid.uuid4(),
            )

    async def test_two_holds_cannot_exceed_balance(self, db, user_factory):
        """Нельзя подать две заявки на вывод на всю сумму."""
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)
        await fin.deposit_from_external(
            db, account=account, amount_minor=1_000,
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )

        await fin.hold(
            db, account=account, amount_minor=600,
            entry_type=LedgerEntryType.WITHDRAWAL_RESERVE,
            ref_type=LedgerRefType.WITHDRAWAL, ref_id=uuid.uuid4(),
        )
        with pytest.raises(InsufficientFunds):
            await fin.hold(
                db, account=account, amount_minor=600,
                entry_type=LedgerEntryType.WITHDRAWAL_RESERVE,
                ref_type=LedgerRefType.WITHDRAWAL, ref_id=uuid.uuid4(),
            )

    async def test_withdraw_releases_hold_and_debits(self, db, user_factory):
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)
        withdrawal_id = uuid.uuid4()

        await fin.deposit_from_external(
            db, account=account, amount_minor=10_000,
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )
        await fin.hold(
            db, account=account, amount_minor=4_000,
            entry_type=LedgerEntryType.WITHDRAWAL_RESERVE,
            ref_type=LedgerRefType.WITHDRAWAL, ref_id=withdrawal_id,
        )
        await fin.withdraw_to_external(
            db, account=account, amount_minor=4_000,
            ref_type=LedgerRefType.WITHDRAWAL, ref_id=withdrawal_id,
        )

        assert account.balance_minor == 6_000
        assert account.hold_minor == 0
        assert account.available_minor == 6_000

    async def test_double_confirm_does_not_debit_twice(self, db, user_factory):
        """Двойной клик по «подтвердить вывод» не должен списать дважды."""
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)
        withdrawal_id = uuid.uuid4()

        await fin.deposit_from_external(
            db, account=account, amount_minor=10_000,
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )
        await fin.hold(
            db, account=account, amount_minor=4_000,
            entry_type=LedgerEntryType.WITHDRAWAL_RESERVE,
            ref_type=LedgerRefType.WITHDRAWAL, ref_id=withdrawal_id,
        )
        await fin.withdraw_to_external(
            db, account=account, amount_minor=4_000,
            ref_type=LedgerRefType.WITHDRAWAL, ref_id=withdrawal_id,
        )
        again = await fin.withdraw_to_external(
            db, account=account, amount_minor=4_000,
            ref_type=LedgerRefType.WITHDRAWAL, ref_id=withdrawal_id,
        )

        assert again.already_applied is True
        assert account.balance_minor == 6_000


class TestCommissionSplit:
    async def test_p2p_split_end_to_end(self, db, user_factory):
        """
        Полный сценарий сплита из ТЗ: покупатель платит 25 TON на счёт
        платформы, платформа удерживает 2% и начисляет остаток продавцу.
        """
        seller = await user_factory()
        platform = await fin.platform_account(db, TON)
        seller_acc = await fin.user_account(db, seller.id, TON)
        deal_id = uuid.uuid4()

        amount = to_minor(Decimal("25"), TON)
        commission, payout = split_by_bp(amount, 200)

        await fin.deposit_from_external(
            db, account=platform, amount_minor=amount,
            ref_type=LedgerRefType.DEAL, ref_id=deal_id,
        )
        await fin.transfer(
            db, src=platform, dst=seller_acc, amount_minor=payout,
            entry_type=LedgerEntryType.SELLER_ACCRUAL,
            ref_type=LedgerRefType.DEAL, ref_id=deal_id,
        )

        assert seller_acc.balance_minor == to_minor(Decimal("24.5"), TON)
        assert platform.balance_minor == to_minor(Decimal("0.5"), TON)
        assert commission + payout == amount

        report = await fin.reconcile(db)
        assert report.ok


class TestReconcile:
    async def test_clean_ledger_reconciles(self, db, user_factory):
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)
        await fin.deposit_from_external(
            db, account=account, amount_minor=1_234,
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )

        report = await fin.reconcile(db)
        assert report.ok
        assert report.issues == []

    async def test_detects_balance_tampering(self, db, user_factory):
        """
        Если кто-то поменяет баланс в обход журнала (руками в SQL, старым
        кодом), сверка обязана это увидеть.
        """
        user = await user_factory()
        account = await fin.user_account(db, user.id, TON)
        await fin.deposit_from_external(
            db, account=account, amount_minor=1_000,
            ref_type=LedgerRefType.ORDER, ref_id=uuid.uuid4(),
        )

        account.balance_minor = 999_999
        await db.flush()

        report = await fin.reconcile(db)
        assert not report.ok
        assert any(i.field == "balance_minor" for i in report.issues)
