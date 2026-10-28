"""
Токен бота не должен попадать в логи.

Адрес запроса к Telegram содержит токен целиком (https://api.telegram.org/bot<id>:<секрет>/…),
а httpx кладёт этот адрес в текст любой ошибки. Ошибка Telegram («чат не
найден», сеть) попадала в print и в журнал вместе с токеном, и любой, кто
видит логи контейнера, получал полный доступ к боту.

Вычёркивать токен в каждом месте, где ошибка печатается, нельзя: таких мест
десятки (print в сервисах, logger в маршрутах), и новое всегда забудут.
Поэтому один раз на выходе — фильтр журнала и обёртка над stdout/stderr.
"""

from __future__ import annotations

import logging
import re
import sys

# «123456789:AAxxxxxxxx…» — числовой идентификатор бота, двоеточие и секрет
# в 30+ знаков. Время вида 12:34:56 и обычные пары «ключ:значение» не
# подходят: после двоеточия нет длинной строки без пробелов.
# Не «\b» перед цифрами: в адресе токен стоит вплотную к «bot» (…/bot123:AA…),
# и границы слова между буквой и цифрой нет. Нужно только, чтобы перед
# идентификатором не стояла ещё цифра
_TOKEN = re.compile(r"(?<!\d)(\d{6,12}):[A-Za-z0-9_-]{30,}")

REPLACEMENT = r"\1:<скрыто>"


def redact(text: str) -> str:
    return _TOKEN.sub(REPLACEMENT, text)


class TokenFilter(logging.Filter):
    """Вычёркивает токены из сообщения записи, в том числе из аргументов."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True


class _RedactingStream:
    """Обёртка над stdout/stderr: всё, что печатается в процессе, проходит очистку."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        return self._stream.write(redact(text) if isinstance(text, str) else text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def install() -> None:
    """
    Включает очистку. Вызывать один раз при старте, до настройки логирования.

    Повторный вызов безопасен: обёртка поверх обёртки не ставится.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if not isinstance(stream, _RedactingStream):
            setattr(sys, name, _RedactingStream(stream))

    root = logging.getLogger()
    if not any(isinstance(f, TokenFilter) for f in root.filters):
        root.addFilter(TokenFilter())
    for handler in root.handlers:
        if not any(isinstance(f, TokenFilter) for f in handler.filters):
            handler.addFilter(TokenFilter())

    # httpx на уровне INFO пишет адрес каждого запроса — а в нём токен. Ошибки
    # (WARNING и выше) остаются, и очищаются фильтром
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
