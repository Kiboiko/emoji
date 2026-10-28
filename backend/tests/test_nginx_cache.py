"""
Микрокеш публичных ответов в nginx: список адресов должен быть точным.

Кеш держит ответ три секунды и отдаёт его ВСЕМ, кто спросил тот же адрес.
Поэтому в него нельзя попасть ничему, что зависит от пользователя: корзине,
заказам, кабинету, админке. Тест читает настоящий nginx.conf и проверяет
регулярное выражение на конкретных адресах — ошибка здесь это чужая корзина в
ответе другому человеку.
"""

import re
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[2] / "nginx" / "nginx.conf"

pytestmark = pytest.mark.skipif(
    not CONFIG.exists(), reason="nginx.conf не входит в образ бэкенда — тест идёт из репозитория",
)

UUID = "0feb0965-3700-49c8-b7e1-43dc49cdb6e1"


@pytest.fixture(scope="module")
def cached_location() -> re.Pattern:
    text = CONFIG.read_text(encoding="utf-8")
    # Выражение обязано быть в кавычках: «{36}» без них nginx читает как начало
    # блока конфигурации и не запускается
    block = re.search(r'location ~ "(\^/api/\(.+?\)\$)" \{', text)
    assert block, "в nginx.conf не найден location с кешем публичного API (в кавычках)"
    return re.compile(block.group(1))


@pytest.mark.parametrize("path", [
    "/api/products",
    f"/api/products/{UUID}",
    "/api/categories",
    "/api/stores",
    f"/api/stores/seller/{UUID}",
    f"/api/stores/channel/{UUID}",
    "/api/settings/public",
    "/api/terms",
])
def test_public_endpoints_are_cached(cached_location, path):
    assert cached_location.match(path)


@pytest.mark.parametrize("path", [
    # данные пользователя
    "/api/cart", f"/api/cart/{UUID}", "/api/orders", f"/api/orders/{UUID}",
    "/api/p2p/seller/me", "/api/p2p/seller/listings", "/api/p2p/deals",
    "/api/withdrawals/my", "/api/users/me", "/api/auth/telegram",
    "/api/terms/status", "/api/terms/accept", "/api/subscriptions/my",
    # админка и персонал
    "/api/products/admin", "/api/categories/all", "/api/admin/p2p/listings",
    "/api/admin/staff/moderators", "/api/admin/auth/login", "/api/reviews/admin/all",
    "/api/withdrawals/admin/all",
    # вложенное и похожее по префиксу
    f"/api/products/{UUID}/anything", "/api/products/admin/extra", "/api/storesX",
    "/api/internal/moderate-listing", "/api/reviews", "/ws",
    # путь с произвольным окончанием
    "/api/products/not-a-uuid", f"/api/categories/{UUID}",
])
def test_private_and_admin_endpoints_are_never_cached(cached_location, path):
    assert not cached_location.match(path), f"{path} попал бы в общий кеш"


def test_cache_does_not_vary_by_user_and_is_short():
    text = CONFIG.read_text(encoding="utf-8")
    block = text[text.index("proxy_cache api_public;") - 400: text.index("proxy_cache_background_update")]
    assert 'proxy_cache_key "$request_method $request_uri";' in block
    assert "proxy_cache_valid 200 3s;" in block
    # Ответ не должен зависеть от токена: он не в ключе и не сегментирует кеш
    assert "$http_authorization" not in block
    # Админка кеш обходит
    assert "proxy_cache_bypass $skip_api_cache;" in block and "proxy_no_cache $skip_api_cache;" in block


def test_cache_serves_stale_instead_of_errors_and_collapses_stampedes():
    text = CONFIG.read_text(encoding="utf-8")
    assert "proxy_cache_lock on;" in text
    assert re.search(r"proxy_cache_use_stale[^;]*http_502", text)


def test_nginx_can_open_as_many_files_as_it_accepts_connections():
    """
    Лимит открытых файлов процесса должен с запасом покрывать соединения.

    В контейнере он 1024, а worker_connections был 2048: на ~500 одновременных
    соединениях дескрипторы кончались, и nginx отвечал 500 на любой запрос,
    включая главную страницу. Каждое соединение — минимум два дескриптора
    (клиент и бэкенд), плюс файлы кеша и статики.
    """
    text = CONFIG.read_text(encoding="utf-8")
    limit = int(re.search(r"worker_rlimit_nofile\s+(\d+);", text).group(1))
    connections = int(re.search(r"worker_connections\s+(\d+);", text).group(1))
    assert limit >= connections * 3, f"дескрипторов {limit} на {connections} соединений: мало"
    assert re.search(r"worker_processes\s+auto;", text)


def test_cached_location_precedes_the_generic_api_location():
    """В nginx регулярное выражение сильнее префикса, но порядок в файле читают люди."""
    text = CONFIG.read_text(encoding="utf-8")
    assert text.index('location ~ "^/api/') < text.index("location /api/ {")
