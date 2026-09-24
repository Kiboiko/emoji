"""
Вход в приложение: подпись Telegram initData, токены, блокировка.

Это единственная дверь в приложение, и до сих пор она не была покрыта ни одним
тестом. Ошибка здесь имеет два исхода, оба тихие: либо подделанный initData
принимается и можно войти за чужого человека, либо проверка ломается и не
входит никто.

Проверка срока годности появилась не сразу: изначально `auth_date`
игнорировался, и перехваченный initData работал бессрочно.
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from config import settings
from utils import auth

# Метка asyncio ставится точечно на класс с асинхронными тестами: в этом файле
# большинство проверок синхронные, и общая метка на модуль засыпала бы прогон
# предупреждениями.

BOT_TOKEN = "123456:TEST-TOKEN-FOR-SIGNATURE-CHECKS"

DEFAULT_USER = {
    "id": 973231400,
    "username": "buyer",
    "first_name": "Иван",
    "language_code": "ru",
}


def _sign(fields: dict[str, str], token: str) -> str:
    """Подпись по алгоритму Telegram: HMAC от отсортированных пар."""
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()


def make_init_data(
    *,
    token: str = BOT_TOKEN,
    auth_date: int | None = None,
    user: dict | None = None,
    **overrides: str,
) -> str:
    """Собирает подписанный initData, как его прислал бы Telegram."""
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHtest",
        "user": json.dumps(user if user is not None else DEFAULT_USER,
                           separators=(",", ":"), ensure_ascii=False),
    }
    fields.update(overrides)
    return urlencode({**fields, "hash": _sign(fields, token)})


def make_init_data_with_signature(*, token: str = BOT_TOKEN) -> str:
    """
    initData с полем signature — так его присылают свежие клиенты Telegram.

    signature это отдельная подпись Ed25519, которой данные можно проверить
    без токена бота. В расчёт HMAC она ВХОДИТ наравне с остальными полями:
    из строки убирается только hash. Тест моделирует именно это, потому что
    обратное предположение однажды сломало вход на проде.
    """
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHtest",
        "signature": "3S1Cg7c0Vb1cQpKQ2_fake_ed25519_signature",
        "user": json.dumps(DEFAULT_USER, separators=(",", ":"), ensure_ascii=False),
    }
    return urlencode({**fields, "hash": _sign(fields, token)})


@pytest.fixture(autouse=True)
def bot_token(monkeypatch):
    """Подставляем известный токен: подпись считается именно от него."""
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", BOT_TOKEN, raising=False)


# ---------------------------------------------------------------------------
# Подпись initData
# ---------------------------------------------------------------------------

class TestInitDataSignature:

    def test_valid_data_is_accepted(self):
        result = auth.validate_telegram_webapp_data(make_init_data())

        assert result["telegram_id"] == 973231400
        assert result["username"] == "buyer"
        assert result["first_name"] == "Иван"
        assert result["language_code"] == "ru"

    def test_tampered_field_is_rejected(self):
        """
        Подмена данных после подписи не проходит.

        Самая опасная атака: взять свой настоящий initData и поменять в нём id
        на чужой. Подпись считается от всех полей, поэтому не сходится.
        """
        original = make_init_data()
        forged = original.replace("973231400", "111111111")

        assert forged != original
        with pytest.raises(ValueError):
            auth.validate_telegram_webapp_data(forged)

    def test_signature_from_another_bot_is_rejected(self):
        """initData, подписанный чужим ботом, не принимается."""
        with pytest.raises(ValueError):
            auth.validate_telegram_webapp_data(make_init_data(token="999:OTHER-BOT"))

    def test_missing_hash_is_rejected(self):
        without_hash = urlencode({"auth_date": str(int(time.time())), "user": "{}"})

        with pytest.raises(ValueError):
            auth.validate_telegram_webapp_data(without_hash)

    def test_garbage_is_rejected(self):
        with pytest.raises(ValueError):
            auth.validate_telegram_webapp_data("не похоже на initData")


# ---------------------------------------------------------------------------
# Срок годности
# ---------------------------------------------------------------------------

class TestInitDataFreshness:

    def test_expired_init_data_is_rejected(self):
        """
        Просроченный initData не пускает даже с правильной подписью.

        Подпись у перехваченного initData верна всегда — она не протухает сама.
        Единственное, что делает кражу бессмысленной, — это проверка возраста.
        """
        old = int(time.time()) - settings.INITDATA_MAX_AGE_SECONDS - 60

        with pytest.raises(ValueError):
            auth.validate_telegram_webapp_data(make_init_data(auth_date=old))

    def test_data_just_within_limit_is_accepted(self):
        fresh_enough = int(time.time()) - settings.INITDATA_MAX_AGE_SECONDS + 120

        result = auth.validate_telegram_webapp_data(make_init_data(auth_date=fresh_enough))

        assert result["telegram_id"] == 973231400

    def test_small_clock_skew_is_tolerated(self):
        """
        Часы клиента могут немного спешить.

        Без допуска люди с чуть неточным временем на телефоне не смогли бы
        войти вообще — и понять причину со стороны невозможно.
        """
        slightly_ahead = int(time.time()) + 60

        result = auth.validate_telegram_webapp_data(make_init_data(auth_date=slightly_ahead))

        assert result["telegram_id"] == 973231400

    def test_far_future_auth_date_is_rejected(self):
        """Час «из будущего» — это попытка обойти проверку возраста."""
        far_ahead = int(time.time()) + 3600

        with pytest.raises(ValueError):
            auth.validate_telegram_webapp_data(make_init_data(auth_date=far_ahead))

    def test_missing_auth_date_is_rejected(self):
        fields = {"query_id": "AAHtest", "user": json.dumps(DEFAULT_USER)}
        signed = urlencode({**fields, "hash": _sign(fields, BOT_TOKEN)})

        with pytest.raises(ValueError):
            auth.validate_telegram_webapp_data(signed)

    def test_non_numeric_auth_date_is_rejected(self):
        fields = {"auth_date": "вчера", "user": json.dumps(DEFAULT_USER)}
        signed = urlencode({**fields, "hash": _sign(fields, BOT_TOKEN)})

        with pytest.raises(ValueError):
            auth.validate_telegram_webapp_data(signed)


# ---------------------------------------------------------------------------
# Токены
# ---------------------------------------------------------------------------

class TestTokens:

    def test_access_token_round_trip(self):
        token = auth.create_access_token({"user_id": "abc", "is_admin": False})

        payload = auth.decode_access_token(token)

        assert payload["user_id"] == "abc"
        assert payload["is_admin"] is False

    def test_expired_token_is_rejected(self):
        token = auth.create_access_token({"user_id": "abc"}, expires_delta=timedelta(seconds=-10))

        with pytest.raises(ValueError):
            auth.decode_access_token(token)

    def test_token_signed_with_another_key_is_rejected(self, monkeypatch):
        """Смена ключа подписи обесценивает все ранее выданные токены."""
        token = auth.create_access_token({"user_id": "abc"})
        monkeypatch.setattr(settings, "SECRET_KEY", "совершенно другой ключ")

        with pytest.raises(ValueError):
            auth.decode_access_token(token)

    def test_access_token_is_not_accepted_as_refresh(self):
        """
        Токен доступа нельзя предъявить вместо refresh-токена.

        Иначе коротким токеном можно было бы бесконечно продлевать сессию.
        """
        access = auth.create_access_token({"user_id": "abc"})

        with pytest.raises(ValueError):
            auth.decode_refresh_token(access)

    def test_refresh_token_round_trip(self):
        refresh = auth.create_refresh_token({"user_id": "abc"})

        payload = auth.decode_refresh_token(refresh)

        assert payload["type"] == "refresh"
        assert payload["user_id"] == "abc"

    def test_referral_codes_are_unique_enough(self):
        codes = {auth.generate_referral_code() for _ in range(500)}

        assert len(codes) == 500


# ---------------------------------------------------------------------------
# Проверка пароля
# ---------------------------------------------------------------------------

class TestPasswords:

    def test_hash_verifies(self):
        hashed = auth.get_password_hash("правильный пароль")

        assert auth.verify_password("правильный пароль", hashed) is True
        assert auth.verify_password("неправильный", hashed) is False

    def test_same_password_hashes_differently(self):
        """Соль у каждого хеша своя, одинаковые пароли выглядят по-разному."""
        assert auth.get_password_hash("пароль") != auth.get_password_hash("пароль")


# ---------------------------------------------------------------------------
# Дверь в API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCurrentUser:

    async def test_missing_header_gives_401(self, db):
        """
        Именно 401, а не 422.

        Клиенты считают признаком протухшей сессии 401 и по нему обновляют
        токен. При 422 админка показывала бы непонятную ошибку вместо входа.
        """
        with pytest.raises(HTTPException) as exc:
            await auth.get_current_user(authorization=None, db=db)

        assert exc.value.status_code == 401

    async def test_wrong_scheme_gives_401(self, db):
        with pytest.raises(HTTPException) as exc:
            await auth.get_current_user(authorization="Basic dXNlcjpwYXNz", db=db)

        assert exc.value.status_code == 401

    async def test_garbage_token_gives_401(self, db):
        with pytest.raises(HTTPException) as exc:
            await auth.get_current_user(authorization="Bearer не-токен", db=db)

        assert exc.value.status_code == 401

    async def test_valid_token_returns_user(self, db, user_factory):
        user = await user_factory(username="normal")
        token = auth.create_access_token({"user_id": str(user.id)})

        found = await auth.get_current_user(authorization=f"Bearer {token}", db=db)

        assert found.id == user.id

    async def test_deleted_user_gives_404(self, db):
        token = auth.create_access_token({"user_id": str(uuid.uuid4())})

        with pytest.raises(HTTPException) as exc:
            await auth.get_current_user(authorization=f"Bearer {token}", db=db)

        assert exc.value.status_code == 404

    async def test_blocked_user_is_refused(self, db, user_factory):
        """
        Блокировка действует немедленно, а не с истечением токена.

        Колонка `is_blocked` существовала с первой миграции, но не проверялась
        нигде: заблокированный человек продолжал покупать и торговать. Проверка
        стоит именно здесь, на каждом запросе, — иначе с недельным сроком жизни
        токена блокировка начинала бы работать через неделю.
        """
        blocked = await user_factory(username="blocked", is_blocked=True)
        token = auth.create_access_token({"user_id": str(blocked.id)})

        with pytest.raises(HTTPException) as exc:
            await auth.get_current_user(authorization=f"Bearer {token}", db=db)

        # 403, а не 401: по 401 клиент пойдёт перелогиниваться по кругу
        assert exc.value.status_code == 403

    async def test_token_without_user_id_gives_401(self, db):
        token = auth.create_access_token({"whatever": "нет идентификатора"})

        with pytest.raises(HTTPException) as exc:
            await auth.get_current_user(authorization=f"Bearer {token}", db=db)

        assert exc.value.status_code == 401

    async def test_require_admin_refuses_regular_user(self, db, user_factory):
        user = await user_factory(username="not_admin")

        with pytest.raises(HTTPException) as exc:
            await auth.require_admin(user=user)

        assert exc.value.status_code == 403

    async def test_require_admin_passes_admin(self, db, user_factory):
        admin = await user_factory(username="real_admin", is_admin=True)

        assert (await auth.require_admin(user=admin)).id == admin.id


def test_signature_field_does_not_break_the_check():
    """
    Клиент, присылающий signature, должен заходить.

    Вход на проде сломался, когда signature исключили из data-check-string:
    HMAC перестал сходиться у всех, кто это поле присылает. Правильно —
    убирать из строки один только hash.
    """
    data = auth.validate_telegram_webapp_data(make_init_data_with_signature())

    assert data["telegram_id"] == DEFAULT_USER["id"]
    assert data["username"] == DEFAULT_USER["username"]


def test_signature_does_not_let_a_forged_hash_through():
    """Исключение signature из проверки не должно ослаблять саму проверку."""
    forged = make_init_data_with_signature(token="999:WRONG-TOKEN")

    with pytest.raises(ValueError):
        auth.validate_telegram_webapp_data(forged)
