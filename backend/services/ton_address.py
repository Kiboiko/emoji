"""
Адреса TON: проверка и приведение к одному виду.

Адрес выплаты приходит из TonConnect — кошелёк, который человек подключил
в приложении. Это не значит, что ему можно верить: запрос к серверу
отправляет приложение, а не кошелёк. Поэтому адрес проверяется здесь:
опечатка или мусор в нём — это деньги, ушедшие в никуда.

Два вида записи:
  * «дружественный» — 48 символов base64 / base64url: флаги, воркчейн,
    хеш и контрольная сумма CRC16. Его показывают кошельки (EQ…, UQ…, 0Q…);
  * «сырой» — «воркчейн:hex-хеш», как его отдаёт индексер.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass

_RAW = re.compile(r"^(-1|0):([0-9a-fA-F]{64})$")

BOUNCEABLE = 0x11
NON_BOUNCEABLE = 0x51
TESTNET_FLAG = 0x80


class AddressError(ValueError):
    pass


@dataclass(frozen=True)
class TonAddress:
    workchain: int
    hash: bytes
    bounceable: bool = True
    testnet: bool = False

    @property
    def raw(self) -> str:
        return f"{self.workchain}:{self.hash.hex()}"


def _crc16(data: bytes) -> int:
    """CRC16-XModem — им защищён дружественный адрес."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def parse(address: str) -> TonAddress:
    text = (address or "").strip()

    raw = _RAW.match(text)
    if raw:
        return TonAddress(int(raw.group(1)), bytes.fromhex(raw.group(2)))

    if len(text) != 48:
        raise AddressError("Неверная длина адреса TON")
    try:
        data = base64.urlsafe_b64decode(text.replace("+", "-").replace("/", "_"))
    except (ValueError, TypeError):
        raise AddressError("Адрес TON записан неверно")
    if len(data) != 36:
        raise AddressError("Адрес TON записан неверно")
    if _crc16(data[:34]) != int.from_bytes(data[34:], "big"):
        raise AddressError("В адресе TON ошибка: не сходится контрольная сумма")

    tag = data[0]
    testnet = bool(tag & TESTNET_FLAG)
    tag &= ~TESTNET_FLAG
    if tag not in (BOUNCEABLE, NON_BOUNCEABLE):
        raise AddressError("Неизвестный тип адреса TON")
    workchain = data[1] if data[1] < 128 else data[1] - 256
    if workchain not in (0, -1):
        raise AddressError("Неизвестный воркчейн адреса TON")

    return TonAddress(workchain, data[2:34], tag == BOUNCEABLE, testnet)


def is_valid(address: str) -> bool:
    try:
        parse(address)
        return True
    except AddressError:
        return False


def same(a: str, b: str) -> bool:
    """Один и тот же кошелёк, как бы ни были записаны адреса."""
    try:
        return parse(a).raw == parse(b).raw
    except AddressError:
        return False
