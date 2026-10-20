"""
Условия площадки на двух языках: версия одна, текстов два.

Без перевода английскому пользователю отдаётся русский текст — пустая
страница условий хуже страницы на другом языке.
"""

import pytest

from routes import terms as terms_routes
from services import settings_service, terms_service

pytestmark = pytest.mark.asyncio


async def _set(db, key, value):
    await settings_service.set_setting(db, key, value)


async def test_english_user_gets_english_text(db):
    await _set(db, "terms_text", "Условия площадки")
    await _set(db, "terms_text_en", "Platform terms")

    ru = await terms_routes.get_terms(lang="ru", db=db)
    en = await terms_routes.get_terms(lang="en", db=db)

    assert ru["text"] == "Условия площадки" and ru["language"] == "ru"
    assert en["text"] == "Platform terms" and en["language"] == "en"
    # Версия общая: принять условия на одном языке значит принять их целиком
    assert ru["version"] == en["version"]


async def test_missing_translation_falls_back_to_russian(db):
    await _set(db, "terms_text", "Условия площадки")

    en = await terms_routes.get_terms(lang="en", db=db)

    assert en["text"] == "Условия площадки"
    assert en["language"] == "ru"
    assert en["is_empty"] is False


async def test_whitespace_only_translation_counts_as_missing(db):
    await _set(db, "terms_text", "Условия площадки")
    await _set(db, "terms_text_en", "   \n")

    version, text = await terms_service.current(db, "en")

    assert text == "Условия площадки"


async def test_unknown_language_is_russian(db):
    await _set(db, "terms_text", "Условия площадки")
    await _set(db, "terms_text_en", "Platform terms")

    other = await terms_routes.get_terms(lang="de", db=db)

    assert other["language"] == "ru" and other["text"] == "Условия площадки"


async def test_empty_terms_are_reported_empty_in_both_languages(db):
    for lang in ("ru", "en"):
        assert (await terms_routes.get_terms(lang=lang, db=db))["is_empty"] is True
