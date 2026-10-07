"""Денежная арифметика: округления, деление комиссии, запрет float."""

from decimal import Decimal

import pytest

from services.money import (
    UnknownCurrency, bp_to_percent, format_amount, format_ton_short, from_minor,
    percent_to_bp, split_by_bp, to_minor,
)


class TestConversion:
    def test_ton_uses_nanotons(self):
        assert to_minor(Decimal("1"), "TON") == 1_000_000_000
        assert to_minor(Decimal("24.5"), "TON") == 24_500_000_000

    def test_usd_uses_cents(self):
        assert to_minor(Decimal("12.34"), "USD") == 1234

    def test_roundtrip(self):
        for value in ("0.01", "1", "999999.99"):
            assert from_minor(to_minor(Decimal(value), "USD"), "USD") == Decimal(value)

    def test_float_is_rejected(self):
        # Главная защита слоя: float в деньгах не должен пролезть даже случайно
        with pytest.raises(TypeError):
            to_minor(12.34, "USD")

    def test_binary_float_artifacts_do_not_leak(self):
        # 0.1 + 0.2 == 0.30000000000000004 в двоичном float.
        # Через str() -> Decimal получаем ровно 30 центов.
        assert to_minor(Decimal(str(0.1 + 0.2)), "USD") == 30

    def test_rounds_down_never_gives_free_money(self):
        # Система не должна "дорисовывать" денег, которых не было
        assert to_minor(Decimal("0.019"), "USD") == 1
        assert to_minor(Decimal("0.999"), "USD") == 99

    def test_unknown_currency(self):
        with pytest.raises(UnknownCurrency):
            to_minor(Decimal("1"), "BTC")


class TestSplitByBp:
    def test_example_from_spec(self):
        """Пример заказчика: товар 25 TON, комиссия 2% -> 0.5 и 24.5."""
        amount = to_minor(Decimal("25"), "TON")
        commission, seller = split_by_bp(amount, 200)

        assert from_minor(commission, "TON") == Decimal("0.5")
        assert from_minor(seller, "TON") == Decimal("24.5")

    @pytest.mark.parametrize(
        "amount,bp",
        [(1, 200), (3, 3333), (7, 1), (99, 4999), (10**9 + 1, 271), (12345, 9999)],
    )
    def test_nothing_is_ever_lost(self, amount, bp):
        """
        Ключевой инвариант: доля + остаток ВСЕГДА равны исходной сумме.
        Если бы обе части округлялись независимо, на неделимых суммах
        появлялись бы потерянные или лишние единицы.
        """
        share, rest = split_by_bp(amount, bp)
        assert share + rest == amount
        assert share >= 0 and rest >= 0

    def test_indivisible_amount_favours_the_seller(self):
        # 1 нанотон и комиссия 2%: платформе 0, продавцу всё.
        # Округление вниз у доли платформы — сознательный выбор.
        assert split_by_bp(1, 200) == (0, 1)

    def test_zero_and_full(self):
        assert split_by_bp(1000, 0) == (0, 1000)
        assert split_by_bp(1000, 10_000) == (1000, 0)

    def test_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            split_by_bp(1000, 10_001)
        with pytest.raises(ValueError):
            split_by_bp(-1, 200)


class TestPercentHelpers:
    def test_bp_to_percent(self):
        assert bp_to_percent(200) == Decimal("2.00")
        assert bp_to_percent(300) == Decimal("3.00")
        assert bp_to_percent(250) == Decimal("2.50")

    def test_percent_to_bp(self):
        assert percent_to_bp(Decimal("2")) == 200
        assert percent_to_bp(Decimal("2.5")) == 250

    def test_percent_roundtrip(self):
        for bp in (0, 1, 200, 333, 10_000):
            assert percent_to_bp(bp_to_percent(bp)) == bp

    def test_format(self):
        assert format_amount(24_500_000_000, "TON") == "24.5 TON"
        assert format_amount(1_000_000_000, "TON") == "1 TON"
        assert format_amount(1234, "USD") == "12.34 USD"

    def test_short_ton_for_people(self):
        """В сообщениях людям — без хвоста из девяти знаков."""
        assert format_ton_short(6_535_948) == "0.0065 Gram"
        assert format_ton_short(61_783_440) == "0.0618 Gram"
        assert format_ton_short(14_553_000_000) == "14.55 Gram"
        assert format_ton_short(100_000_000_000) == "100 Gram"
        assert format_ton_short(12_300) == "0.000012 Gram"     # мелочь не в ноль
        assert format_ton_short(0) == "0 Gram"
