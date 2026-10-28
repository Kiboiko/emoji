"""
Токен бота не должен попадать в логи: адрес запроса к Telegram содержит его
целиком, а httpx кладёт этот адрес в текст любой ошибки.
"""

import io
import logging

import httpx
import pytest

from utils import log_redact

pytestmark = pytest.mark.asyncio

# Выдуманный токен нужной формы
TOKEN = "8123456789:AAFexampleExampleExampleExample12345"
URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


async def test_token_is_removed_from_text():
    cleaned = log_redact.redact(f"Client error '400 Bad Request' for url '{URL}'")

    assert TOKEN not in cleaned
    assert "AAFexample" not in cleaned
    # Идентификатор бота остаётся — по нему видно, о каком боте речь
    assert "8123456789:<скрыто>" in cleaned


async def test_file_download_url_is_cleaned_too():
    cleaned = log_redact.redact(f"https://api.telegram.org/file/bot{TOKEN}/photos/file_1.jpg")
    assert TOKEN not in cleaned


@pytest.mark.parametrize("harmless", [
    "12:34:56 запрос выполнен",
    "user:password",
    "2026-10-20T19:26:47+03:00",
    "ratio 3:1 and 10:00",
    "uuid 0feb0965-3700-49c8-b7e1-43dc49cdb6e1",
    "https://miniapp.funshop.store/api/products?limit=40",
])
async def test_ordinary_text_is_not_touched(harmless):
    assert log_redact.redact(harmless) == harmless


async def test_logging_filter_cleans_message_and_arguments():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(log_redact.TokenFilter())
    logger = logging.getLogger("redact-test")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.warning("не отправлено: %s", URL)
        logger.warning(f"прямо в строке {URL}")
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert TOKEN not in output and "AAFexample" not in output
    assert output.count("<скрыто>") == 2


async def test_stream_wrapper_cleans_print_output():
    sink = io.StringIO()
    wrapped = log_redact._RedactingStream(sink)

    print(f"[TELEGRAM] ERROR sending to 5171232113: {URL}", file=wrapped)

    assert TOKEN not in sink.getvalue()
    assert "ERROR sending to 5171232113" in sink.getvalue()


async def test_real_httpx_error_text_is_cleaned():
    """Именно такая ошибка и приходит из httpx при ответе Telegram 400."""
    request = httpx.Request("POST", URL)
    response = httpx.Response(400, request=request)
    with pytest.raises(httpx.HTTPStatusError) as raised:
        response.raise_for_status()

    assert TOKEN in str(raised.value), "тест не воспроизводит утечку"
    assert TOKEN not in log_redact.redact(str(raised.value))


async def test_install_is_idempotent_and_keeps_streams_usable(capsys):
    import sys
    log_redact.install()
    log_redact.install()

    assert not isinstance(sys.stdout._stream, log_redact._RedactingStream)
    print("обычная строка")
    assert hasattr(sys.stdout, "flush")
