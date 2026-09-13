from pydantic import BaseModel


class PaymentStatusResponse(BaseModel):
    """Статус оплаты заказа."""
    status: str
    paid: bool


class TonTransactionRequest(BaseModel):
    """
    Данные для TON Connect sendTransaction.

    Суммы строками, а не числами: JavaScript теряет точность на числах больше
    2^53, а нанотоны легко выходят за этот предел (1 TON = 1e9, крупный
    заказ — уже сотни миллиардов).
    """
    address: str
    amount_nano: str
    amount_ton: str
    comment: str
    valid_until: int
    network: str
    rate_usd_per_ton: str
    usd_amount: str
