"""
Денежная арифметика.

Единственное место в проекте, где допустимо переводить деньги между
человекочитаемым видом и хранимым. Правила:

  * в БД деньги хранятся ТОЛЬКО целыми числами в минорных единицах
    (BigInteger). Для TON минорная единица — нанотон (1e-9 TON),
    для USD — цент (1e-2 USD);
  * float в денежной логике запрещён. В наследованном коде баланс лежал в
    `users.referral_earnings` типа Float — так накапливается погрешность,
    и при сплите на несколько получателей копейки начинают теряться;
  * проценты задаются в базисных пунктах (bp): 1 bp = 0.01%, значит
    2% = 200 bp, 3% = 300 bp. Это позволяет хранить настройки комиссий
    целыми числами и не округлять дважды.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Final


# Знаков после запятой у каждой валюты
DECIMALS: Final[dict[str, int]] = {
    "TON": 9,   # нанотоны
    "USD": 2,   # центы
}

BP_DENOMINATOR: Final[int] = 10_000  # 100% = 10000 bp


class UnknownCurrency(ValueError):
    pass


def _scale(currency: str) -> int:
    try:
        return 10 ** DECIMALS[currency]
    except KeyError:
        raise UnknownCurrency(f"Неизвестная валюта: {currency!r}")


def to_minor(amount: Decimal | int | str, currency: str) -> int:
    """
    Человекочитаемая сумма -> минорные единицы.

    Округление вниз (ROUND_DOWN) сознательно: система никогда не должна
    «дорисовать» пользователю денег, которых не было.
    """
    if isinstance(amount, float):
        raise TypeError(
            "float в денежной арифметике запрещён — передавайте Decimal или str"
        )
    value = Decimal(amount) if not isinstance(amount, Decimal) else amount
    return int((value * _scale(currency)).to_integral_value(rounding=ROUND_DOWN))


def from_minor(amount_minor: int, currency: str) -> Decimal:
    """Минорные единицы -> Decimal для показа пользователю."""
    return Decimal(amount_minor) / Decimal(_scale(currency))


def format_amount(amount_minor: int, currency: str) -> str:
    """Например: 24500000000 нанотон, TON -> '24.5 TON'."""
    value = from_minor(amount_minor, currency).normalize()
    # normalize() у целых даёт экспоненциальную запись (2E+1) — разворачиваем
    if value == value.to_integral_value():
        value = value.quantize(Decimal(1))
    return f"{value} {currency}"


def format_ton_short(amount_nano: int) -> str:
    """
    TON для людей: без хвоста из девяти знаков.

    «0.006535948 TON» в сообщении читается как ошибка, а не как сумма. От
    единицы — два знака после точки, меньше — четыре, совсем мелочь — две
    значащие цифры, чтобы не превратиться в ноль. Считать по этому нельзя —
    только показывать; точные суммы — format_amount и минорные единицы.
    """
    value = from_minor(amount_nano, "TON")
    if value == 0:
        return "0 TON"
    magnitude = abs(value)
    if magnitude >= 1:
        places = 2
    elif magnitude >= Decimal("0.0001"):
        places = 4
    else:
        # Две значащие цифры: 0.0000123 → 0.000012
        places = -magnitude.adjusted() + 1
    rounded = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    text = format(rounded.normalize(), "f")
    return f"{text} TON"


def split_by_bp(amount_minor: int, bp: int) -> tuple[int, int]:
    """
    Делит сумму на долю (bp) и остаток.

    Возвращает (доля, остаток). Доля округляется вниз, остаток получает всё
    остальное — поэтому доля + остаток ВСЕГДА равны исходной сумме, ни один
    нанотон не теряется и не появляется из воздуха.

    >>> split_by_bp(25_000_000_000, 200)     # 25 TON, комиссия 2%
    (500000000, 24500000000)                 # 0.5 TON и 24.5 TON
    """
    if amount_minor < 0:
        raise ValueError("Сумма для разделения не может быть отрицательной")
    if not 0 <= bp <= BP_DENOMINATOR:
        raise ValueError(f"bp вне диапазона 0..{BP_DENOMINATOR}: {bp}")

    share = amount_minor * bp // BP_DENOMINATOR
    return share, amount_minor - share


def bp_to_percent(bp: int) -> Decimal:
    """200 bp -> Decimal('2.00') — для показа в интерфейсе."""
    return (Decimal(bp) / Decimal(100)).quantize(Decimal("0.01"))


def percent_to_bp(percent: Decimal | int | str) -> int:
    """Decimal('2.5') -> 250 bp — для приёма значения из админки."""
    if isinstance(percent, float):
        raise TypeError("float запрещён — передавайте Decimal или str")
    value = Decimal(percent) if not isinstance(percent, Decimal) else percent
    return int((value * 100).to_integral_value(rounding=ROUND_DOWN))
