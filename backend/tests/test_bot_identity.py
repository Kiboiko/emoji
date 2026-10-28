"""
Проверка при старте: токен бота принадлежит тому боту, из которого открывают
приложение. Расхождение ломает вход у всех (Invalid hash), поэтому оно должно
быть видно в журнале, а сама проверка не должна ничего ронять.
"""

import logging

import pytest

from config import settings
from services import bot_identity
from services.telegram_service import TelegramApiError

pytestmark = pytest.mark.asyncio


def _fake_call(result=None, error=None):
    async def call(method, payload):
        assert method == "getMe"
        if error is not None:
            raise error
        return result
    return call


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "111111111:test-token-not-real-test-token-not-real")
    monkeypatch.setattr(settings, "VITE_BOT_USERNAME", "Funshop_bot")


async def test_matching_bot_logs_info_only(monkeypatch, caplog):
    monkeypatch.setattr(bot_identity, "_call", _fake_call({"id": 111, "username": "Funshop_bot"}))
    with caplog.at_level(logging.INFO, logger="services.bot_identity"):
        assert await bot_identity.check_bot_identity() == "Funshop_bot"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert "@Funshop_bot" in caplog.text


async def test_username_comparison_ignores_case_and_at(monkeypatch, caplog):
    monkeypatch.setattr(settings, "VITE_BOT_USERNAME", "@funshop_BOT")
    monkeypatch.setattr(bot_identity, "_call", _fake_call({"id": 111, "username": "Funshop_bot"}))
    with caplog.at_level(logging.INFO, logger="services.bot_identity"):
        await bot_identity.check_bot_identity()
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_token_of_another_bot_is_reported_loudly(monkeypatch, caplog):
    monkeypatch.setattr(bot_identity, "_call", _fake_call({"id": 222, "username": "DealGuard_app"}))
    with caplog.at_level(logging.INFO, logger="services.bot_identity"):
        assert await bot_identity.check_bot_identity() == "DealGuard_app"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "DealGuard_app" in errors[0].getMessage() and "Funshop_bot" in errors[0].getMessage()
    assert "Invalid hash" in errors[0].getMessage()


async def test_rejected_token_is_an_error_not_a_crash(monkeypatch, caplog):
    monkeypatch.setattr(bot_identity, "_call", _fake_call(error=TelegramApiError("getMe", "Unauthorized", 401)))
    with caplog.at_level(logging.INFO, logger="services.bot_identity"):
        assert await bot_identity.check_bot_identity() is None
    assert [r for r in caplog.records if r.levelno == logging.ERROR]


async def test_network_failure_is_only_a_warning(monkeypatch, caplog):
    monkeypatch.setattr(bot_identity, "_call", _fake_call(error=ConnectionError("no route")))
    with caplog.at_level(logging.INFO, logger="services.bot_identity"):
        assert await bot_identity.check_bot_identity() is None
    levels = {r.levelno for r in caplog.records}
    assert logging.WARNING in levels and logging.ERROR not in levels


async def test_missing_token_is_reported(monkeypatch, caplog):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    with caplog.at_level(logging.INFO, logger="services.bot_identity"):
        assert await bot_identity.check_bot_identity() is None
    assert [r for r in caplog.records if r.levelno == logging.ERROR]


async def test_no_configured_username_means_nothing_to_compare(monkeypatch, caplog):
    monkeypatch.setattr(settings, "VITE_BOT_USERNAME", "")
    monkeypatch.setattr(bot_identity, "_call", _fake_call({"id": 222, "username": "AnyBot"}))
    with caplog.at_level(logging.INFO, logger="services.bot_identity"):
        assert await bot_identity.check_bot_identity() == "AnyBot"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_the_token_itself_never_reaches_the_log(monkeypatch, caplog):
    monkeypatch.setattr(bot_identity, "_call", _fake_call({"id": 222, "username": "DealGuard_app"}))
    with caplog.at_level(logging.DEBUG):
        await bot_identity.check_bot_identity()
    assert settings.TELEGRAM_BOT_TOKEN not in caplog.text
