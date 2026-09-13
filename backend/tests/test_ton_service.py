"""
Логика приёма TON: конверсия по курсу и сопоставление транзакции с платежом.

Сетевых вызовов здесь нет — проверяется чистая логика, от которой зависит,
выдадим мы товар или нет.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from services import ton_service
from services.ton_service import NANO, OnChainTx, RateUnavailable, match_payment


def tx(comment: str, value_nano: int, utime: int, lt: int = 1, hash_: str = "h") -> OnChainTx:
    return OnChainTx(
        tx_hash=hash_, lt=lt, utime=utime,
        source="EQTestSender", value_nano=value_nano, comment=comment,
    )


class TestUsdToNano:
    def test_basic(self):
        # 10 USD при курсе 2.5 USD за TON = 4 TON
        assert ton_service.usd_to_nano(Decimal("10"), Decimal("2.5")) == 4 * NANO

    def test_rounds_up(self):
        """
        Округление ВВЕРХ обязательно. При округлении вниз пользователь платит
        на несколько нанотон меньше ожидаемого, и его платёж попадает в
        underpaid — товар не выдаётся из-за копеечной разницы.
        """
        # 1 USD / 3 USD за TON = 0.333... TON, в нанотонах не делится нацело
        nano = ton_service.usd_to_nano(Decimal("1"), Decimal("3"))
        assert nano == 333_333_334          # не ...333
        assert Decimal(nano) / NANO * Decimal("3") >= Decimal("1")

    def test_rejects_bad_rate(self):
        with pytest.raises(RateUnavailable):
            ton_service.usd_to_nano(Decimal("10"), Decimal("0"))
        with pytest.raises(RateUnavailable):
            ton_service.usd_to_nano(Decimal("10"), Decimal("-1"))


class TestPaymentComment:
    def test_format_and_uniqueness(self):
        comments = {ton_service.generate_payment_comment() for _ in range(500)}
        assert len(comments) == 500          # коллизий нет
        for c in comments:
            assert c.startswith("MP-")
            assert len(c) <= 64              # влезает в колонку

    def test_does_not_leak_internal_ids(self):
        # Комментарий виден всем в блокчейне — внутренние UUID туда попадать
        # не должны
        c = ton_service.generate_payment_comment()
        assert "-" not in c[3:]              # не UUID


class TestMatchPayment:
    def setup_method(self):
        self.now = datetime(2026, 9, 13, 12, 0, 0)
        self.start = self.now - timedelta(minutes=5)
        self.end = self.now + timedelta(minutes=30)
        self.ts = int(self.now.timestamp())

    def _match(self, txs, expected=10 * NANO, comment="MP-ABC123"):
        return match_payment(
            txs, comment=comment, expected_nano=expected,
            window_start=self.start, window_end=self.end,
        )

    def test_exact_amount_matches(self):
        result = self._match([tx("MP-ABC123", 10 * NANO, self.ts)])
        assert result.matched
        assert result.tx.value_nano == 10 * NANO

    def test_overpayment_matches(self):
        """Переплата не должна блокировать выдачу товара."""
        result = self._match([tx("MP-ABC123", 15 * NANO, self.ts)])
        assert result.matched

    def test_underpayment_is_flagged_not_matched(self):
        result = self._match([tx("MP-ABC123", 9 * NANO, self.ts)])
        assert not result.matched
        assert result.underpaid
        assert result.tx is not None

    def test_wrong_comment_is_ignored(self):
        """Чужой платёж на тот же адрес не должен закрывать наш заказ."""
        result = self._match([tx("MP-OTHER1", 10 * NANO, self.ts)])
        assert not result.matched
        assert not result.underpaid

    def test_empty_comment_is_ignored(self):
        result = self._match([tx("", 10 * NANO, self.ts)])
        assert not result.matched

    def test_transaction_before_window_is_ignored(self):
        """
        Защита от переиспользования комментария: старый платёж с тем же
        комментарием не должен закрыть новый заказ.
        """
        old = int((self.now - timedelta(days=1)).timestamp())
        result = self._match([tx("MP-ABC123", 10 * NANO, old)])
        assert not result.matched

    def test_transaction_after_window_is_ignored(self):
        late = int((self.now + timedelta(days=1)).timestamp())
        result = self._match([tx("MP-ABC123", 10 * NANO, late)])
        assert not result.matched

    def test_picks_earliest_when_several_match(self):
        result = self._match([
            tx("MP-ABC123", 10 * NANO, self.ts, lt=500, hash_="later"),
            tx("MP-ABC123", 10 * NANO, self.ts, lt=100, hash_="earlier"),
        ])
        assert result.matched
        assert result.tx.tx_hash == "earlier"

    def test_full_amount_wins_over_underpaid(self):
        """Если пришли и недоплата, и полная сумма — засчитываем полную."""
        result = self._match([
            tx("MP-ABC123", 1 * NANO, self.ts, lt=100, hash_="partial"),
            tx("MP-ABC123", 10 * NANO, self.ts, lt=200, hash_="full"),
        ])
        assert result.matched
        assert result.tx.tx_hash == "full"

    def test_no_transactions(self):
        result = self._match([])
        assert not result.matched
        assert not result.underpaid


class TestPaymentWindow:
    def test_window_has_slack_on_both_sides(self):
        locked = datetime(2026, 9, 13, 12, 0, 0)
        expires = locked + timedelta(minutes=15)
        start, end = ton_service.payment_window(locked, expires)

        # Платёж мог уйти чуть раньше фиксации курса и подтвердиться заметно
        # позже истечения счёта — окно обязано это покрывать
        assert start < locked
        assert end > expires
