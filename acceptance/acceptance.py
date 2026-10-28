"""
Приёмочные испытания этапа 1 на копии боевых данных.

Идёт через настоящий nginx и боевой образ бэкенда: HTTP, куки, заголовки,
файлы на диске. Telegram не уходит наружу — отправки пишутся в файл.
Каждая проверка печатает PASS/FAIL; в конце — сводка и результаты нагрузки.
"""
import asyncio
import hashlib
import hmac
import io
import json
import os
import random
import statistics
import sys
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

import httpx
from PIL import Image
from sqlalchemy import text

BASE = os.environ.get("BASE", "http://mp-acc-nginx")
OUTBOX = os.environ.get("OUTBOX", "/outbox/telegram.jsonl")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_USER = os.environ["ADMIN_USERNAME"]
ADMIN_PASS = os.environ["ADMIN_PASSWORD"]
LOAD_SECONDS = int(os.environ.get("LOAD_SECONDS", "45"))
LOAD_USERS = int(os.environ.get("LOAD_USERS", "150"))
LOAD_USERS_REAL = int(os.environ.get("LOAD_USERS_REAL", "300"))
MOD = f"acc_moder_{random.randint(1000, 9999)}"

from database import AsyncSessionLocal  # noqa: E402
from utils.auth import create_access_token  # noqa: E402

RESULTS: list[tuple[str, str, bool, str]] = []
METRICS: dict = {}


def check(section: str, name: str, ok, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append((section, name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    tail = f"   <- {detail}" if (detail and not ok) else (f"   [{detail}]" if detail else "")
    print(f"{mark}  [{section}] {name}{tail}", flush=True)
    return ok


def head(title: str) -> None:
    print(f"\n===== {title} =====", flush=True)


# ---------------------------------------------------------------- утилиты

def png(width=640, height=480, noise=True) -> bytes:
    data = os.urandom(width * height * 3) if noise else bytes([40, 90, 160]) * (width * height)
    buffer = io.BytesIO()
    Image.frombytes("RGB", (width, height), data).save(buffer, "PNG")
    return buffer.getvalue()


def outbox() -> list[dict]:
    try:
        with open(OUTBOX, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        return []


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


async def db_exec(sql: str, **params):
    async with AsyncSessionLocal() as s:
        result = await s.execute(text(sql), params)
        await s.commit()
        try:
            return result.fetchall()
        except Exception:
            return None


async def make_app_user(label: str) -> tuple[str, dict]:
    """Пользователь приложения и его токен — такой же, какой выдаёт вход через Telegram."""
    uid = uuid.uuid4()
    tg = random.randint(7_000_000_000, 7_900_000_000)
    await db_exec(
        "insert into users (id, telegram_id, username, first_name, language_code, is_admin, is_blocked, "
        "referral_code, referral_earnings, created_at, is_moderator, token_version) "
        "values (:id, :tg, :u, :n, 'ru', false, false, :rc, 0, now(), false, 0)",
        id=uid, tg=tg, u=f"acc_{label}", n=f"Acc {label}", rc=f"ACC{uuid.uuid4().hex[:10]}")
    token = create_access_token({"user_id": str(uid), "telegram_id": tg, "is_admin": False})
    return str(uid), {"Authorization": f"Bearer {token}"}


def init_data(token: str, tg_id: int, first_name="Real Flow") -> str:
    """initData, подписанный так же, как это делает Telegram (по токену бота)."""
    user = json.dumps({"id": tg_id, "first_name": first_name, "username": f"flow{tg_id}", "language_code": "ru"},
                      separators=(",", ":"))
    fields = {"auth_date": str(int(time.time())), "query_id": "AAEacceptance", "user": user}
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields, quote_via=quote)


async def main() -> int:
    t_start = time.time()
    c = httpx.AsyncClient(base_url=BASE, timeout=60, follow_redirects=False)

    async def get_fresh(path, **kw):
        """Чтение в обход микрокеша (как делает сама админка): сразу после записи видны свежие данные."""
        headers = {**kw.pop("headers", {}), "Referer": f"{BASE}/admin/check"}
        return await c.get(path, headers=headers, **kw)

    # ================================================================== 0
    head("0. Среда")
    r = await c.get("/health")
    check("среда", "бэкенд отвечает через nginx", r.status_code == 200, r.text[:80])
    rev = (await db_exec("select version_num from alembic_version"))[0][0]
    check("среда", "схема базы на последней миграции", rev == "d5e6f7a8b9c0", rev)
    before = {t: (await db_exec(f"select count(*) from {t}"))[0][0]
              for t in ("users", "products", "orders", "deals", "reviews", "product_listings")}
    print("  данные в копии:", before)
    check("среда", "в копии есть боевые данные", before["users"] > 5 and before["products"] > 5)

    # ================================================================== вход админа и модератора
    head("П.15 / П.13–14. Вход, роли, журналы")
    r = await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS},
                     headers={"X-Forwarded-For": "203.0.113.10", "User-Agent": "acceptance-admin/1.0"})
    check("П.15", "администратор входит паролем из настроек сервера", r.status_code == 200 and r.json().get("role") == "admin",
          f"{r.status_code} {r.text[:100]}")
    admin_token = r.json()["access_token"]
    A = {"Authorization": f"Bearer {admin_token}"}
    cookies = r.headers.get_list("set-cookie")
    cookie = next((x for x in cookies if "admin_refresh_token" in x), "")
    check("П.15", "refresh-кука: HttpOnly, Secure, SameSite=lax", all(k in cookie for k in ("HttpOnly", "Secure", "SameSite=lax")), cookie[:120])
    refresh_cookie = cookie.split("admin_refresh_token=")[1].split(";")[0] if cookie else ""

    r = await c.post("/api/admin/auth/refresh", headers={"Cookie": f"admin_refresh_token={refresh_cookie}"})
    check("П.15", "обновление токена по куке работает", r.status_code == 200 and r.json().get("role") == "admin")

    log = (await c.get("/api/admin/staff/login-log", headers=A)).json()
    mine = [x for x in log["items"] if x["username"] == ADMIN_USER and x["success"]]
    check("П.15", "вход записан в журнал с IP и браузером",
          mine and mine[0]["ip"] == "203.0.113.10" and "acceptance-admin" in (mine[0]["user_agent"] or ""), str(mine[:1]))

    r = await c.post("/api/admin/staff/moderators", headers=A,
                     json={"username": MOD, "password": "Moder-Pass-2026", "display_name": "Модератор Тест"})
    check("П.13–14", "администратор добавляет модератора со своим логином и паролем", r.status_code == 200, r.text[:100])
    moderator_id = r.json().get("id")
    r = await c.post("/api/admin/auth/login", json={"username": MOD, "password": "Moder-Pass-2026"})
    check("П.13–14", "модератор входит со своими данными", r.status_code == 200 and r.json().get("role") == "moderator", r.text[:100])
    M = {"Authorization": f"Bearer {r.json()['access_token']}"}
    claims_ok = False
    try:
        import base64
        payload = json.loads(base64.urlsafe_b64decode(r.json()["access_token"].split(".")[1] + "=="))
        claims_ok = payload.get("is_admin") is False and payload.get("role") == "moderator" and "tv" in payload
    except Exception:
        pass
    check("П.13–14", "токен модератора: не админ, роль moderator, есть версия", claims_ok)

    # --- матрица прав по ВСЕМ маршрутам приложения
    import main as app_main
    from fastapi.routing import APIRoute
    from utils.auth import require_admin, require_staff

    def deps(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from deps(d)

    class Route:
        def __init__(self, path, methods, calls):
            self.path, self.methods, self.calls = path, methods, calls

    def iter_api_routes(app):
        """Маршруты приложения, включая вложенные роутеры (в новых FastAPI они лежат в _IncludedRouter)."""
        for r in app.routes:
            if isinstance(r, APIRoute):
                yield "", r
            elif hasattr(r, "original_router"):
                ctx = getattr(r, "include_context", None)
                prefix = getattr(ctx, "prefix", "") or ""
                for rr in r.original_router.routes:
                    if isinstance(rr, APIRoute):
                        yield prefix, rr

    admin_only, staff_routes, total_routes = [], [], 0
    for prefix, route in iter_api_routes(app_main.app):
        total_routes += 1
        calls = set(deps(route.dependant))
        item = Route(prefix + route.path, route.methods, calls)
        if require_staff in calls:
            staff_routes.append(item)
        elif require_admin in calls:
            admin_only.append(item)
    print(f"  маршрутов в приложении: {total_routes}; только администратору: {len(admin_only)}; администратору и модератору: {len(staff_routes)}")

    # Защита от пустой проверки: обход обязан найти маршруты
    check("П.13–14", "обход нашёл все маршруты приложения (не пустая проверка): не меньше 150, из них не меньше 60 админских",
          total_routes >= 150 and len(admin_only) >= 60, f"{total_routes} / {len(admin_only)}")
    expected_staff = {
        ("GET", "/api/admin/auth/me"), ("POST", "/api/admin/auth/change-password"), ("POST", "/api/admin/auth/logout-all"),
        ("GET", "/api/admin/p2p/listings"), ("POST", "/api/admin/p2p/listings/{listing_id}/moderate"),
        ("GET", "/api/admin/p2p/deals"), ("GET", "/api/admin/p2p/deals/{deal_id}/messages"),
        ("POST", "/api/admin/p2p/deals/{deal_id}/messages"), ("POST", "/api/admin/p2p/deals/{deal_id}/resolve"),
        ("DELETE", "/api/admin/p2p/listings/{listing_id}/images/{image_id}"), ("DELETE", "/api/admin/p2p/sellers/{seller_id}/avatar"),
    }
    actual_staff = {(m, r.path) for r in staff_routes for m in r.methods - {"HEAD", "OPTIONS"}}
    check("П.13–14", "модератору (и администратору) доступны ровно 11 действий: свой пароль и сессии, заявки, споры, удаление фото",
          actual_staff == expected_staff, f"лишнее: {sorted(actual_staff - expected_staff)}; пропало: {sorted(expected_staff - actual_staff)}")

    public_admin = {"/api/admin/auth/login", "/api/admin/auth/refresh", "/api/admin/auth/logout"}
    unguarded = [
        prefix + route.path for prefix, route in iter_api_routes(app_main.app)
        if "/admin" in prefix + route.path and prefix + route.path not in public_admin
        and not ({require_admin, require_staff} & set(deps(route.dependant)))
    ]
    check("П.13–14", "каждый адрес с /admin закрыт общей проверкой администратора или персонала (самодельной или забытой защиты нет)",
          not unguarded, "; ".join(unguarded[:4]))

    def url_of(route):
        path = route.path
        for part in path.split("/"):
            if part.startswith("{"):
                path = path.replace(part, str(uuid.uuid4()))
        return path

    wrong, tested = [], 0
    for route in admin_only:
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            for who, headers, expect in (("аноним", {}, 401), ("модератор", M, 403)):
                resp = await c.request(method, url_of(route), headers=headers, json={} if method != "GET" else None)
                tested += 1
                if resp.status_code != expect:
                    wrong.append(f"{who} {method} {route.path} -> {resp.status_code} (ждали {expect})")
    check("П.13–14", f"модератору и анониму закрыты все разделы администратора ({len(admin_only)} маршрутов, {tested} запросов)",
          not wrong, "; ".join(wrong[:4]))
    METRICS["admin_only_routes"] = len(admin_only)
    METRICS["staff_routes"] = [f"{sorted(r.methods - {'HEAD', 'OPTIONS'})[0]} {r.path}" for r in staff_routes]
    print("  маршруты, доступные модератору:", *METRICS["staff_routes"], sep="\n    ")
    anon_bad = []
    for route in staff_routes:
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            resp = await c.request(method, url_of(route), json={} if method != "GET" else None)
            if resp.status_code != 401:
                anon_bad.append(f"{method} {route.path} -> {resp.status_code}")
    check("П.13–14", "общие с модератором маршруты закрыты для анонима", not anon_bad, "; ".join(anon_bad))
    # Администратору открыто всё чтение
    forb = []
    for route in admin_only:
        if route.methods == {"GET"} or route.methods == {"GET", "HEAD"}:
            resp = await c.get(url_of(route), headers=A)
            if resp.status_code in (401, 403):
                forb.append(f"{route.path} -> {resp.status_code}")
    check("П.13–14", "администратор видит все разделы (GET)", not forb, "; ".join(forb[:3]))

    for path in ("/api/admin/p2p/listings", "/api/admin/p2p/deals"):
        r = await c.get(path, headers=M)
        check("П.13–14", f"модератору открыт {path}", r.status_code == 200, str(r.status_code))
    for path in ("/api/admin/staff/moderators", "/api/admin/staff/audit-log", "/api/admin/staff/login-log",
                 "/api/admin/settings", "/api/admin/finance/accounts", "/api/admin/users"):
        r = await c.get(path, headers=M)
        check("П.13–14", f"модератору закрыт {path}", r.status_code == 403, str(r.status_code))
    r = await c.post("/api/admin/staff/moderators", headers=M, json={"username": "sneaky_one", "password": "Sneaky-Pass-2026"})
    check("П.13–14", "модератор не может завести другого модератора", r.status_code == 403)
    r = await c.get("/api/auth/admin")
    r2 = await c.post("/api/auth/admin", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    r3 = await c.post("/api/auth/dev")
    check("П.15", "старый вход /api/auth/admin удалён, /api/auth/dev не существует",
          r2.status_code in (404, 405) and r3.status_code == 404, f"{r2.status_code}/{r3.status_code}")

    # ================================================================== П.1 категория
    head("П.1. Категория обязательна")
    cats = (await c.get("/api/categories?lang=ru")).json()
    check("П.1", "публичный список категорий не пуст", len(cats) > 0, str(len(cats)))
    legacy_id = uuid.uuid4()
    await db_exec("insert into categories (id, name_ru, name_en, sort_order, created_at) values (:i,'Товары пользователей','User items',200,now())", i=legacy_id)
    cats = (await c.get("/api/categories?lang=ru")).json()
    check("П.1", "служебной «Товары пользователей» нет в публичном списке", all(x["name"] != "Товары пользователей" for x in cats))
    category = cats[0]["id"]

    seller_id, S = await make_app_user("seller")
    r = await c.post("/api/p2p/seller/register", headers=S, json={"display_name": f"AccShop{random.randint(1000, 9999)}", "accept_terms": True})
    check("П.1", "продавец регистрирует магазин", r.status_code == 200, r.text[:100])
    seller_profile = (await c.get("/api/p2p/seller/me", headers=S)).json()
    profile_id = seller_profile["id"]

    body = {"name": "Механическая клавиатура", "name_en": "Mechanical keyboard",
            "description": "Почти новая, в коробке", "description_en": "Almost new, boxed",
            "quantity": 1, "price_usd": "50.00", "accept_terms": True}
    r = await c.post("/api/p2p/seller/listings", headers=S, json=body)
    check("П.1", "создание без категории отклоняется (422)", r.status_code == 422, str(r.status_code))
    r = await c.post("/api/p2p/seller/listings", headers=S, json={**body, "category_id": str(uuid.uuid4())})
    check("П.1", "несуществующая категория отклоняется (400)", r.status_code == 400, f"{r.status_code} {r.text[:80]}")
    r = await c.post("/api/p2p/seller/listings", headers=S, json={**body, "category_id": str(legacy_id)})
    check("П.1", "служебная категория не принимается (400)", r.status_code == 400, f"{r.status_code}")
    r = await c.post("/api/p2p/seller/listings", headers=S, json={**body, "category_id": category})
    check("П.1", "с настоящей категорией заявка создаётся", r.status_code == 200 and r.json()["status"] == "draft", r.text[:100])
    L1 = r.json()["id"]

    # старая заявка без категории (как могла остаться с прошлых времён)
    legacy_cnt_before = (await db_exec("select count(*) from categories where name_en='User items'"))[0][0]
    legacy_listing = uuid.uuid4()
    await db_exec("insert into product_listings (id, seller_id, name, name_en, description, description_en, price_usd, quantity, status, created_at) "
                  "values (:i,:s,'Старая заявка','Old','Заявка без категории','No category',5,1,'DRAFT',now())", i=legacy_listing, s=profile_id)
    await db_exec("insert into listing_images (id, listing_id, url, sort_order) values (gen_random_uuid(), :l, '/uploads/products/placeholder.png', 0)", l=legacy_listing)
    r = await c.post(f"/api/p2p/seller/listings/{legacy_listing}/submit", headers=S)
    check("П.1", "заявку без категории нельзя отправить на проверку", r.status_code == 400, f"{r.status_code} {r.text[:80]}")
    await db_exec("update product_listings set status='PENDING' where id=:i", i=legacy_listing)
    r = await c.post(f"/api/admin/p2p/listings/{legacy_listing}/moderate", headers=M, json={"approve": True})
    check("П.1", "заявку без категории нельзя и одобрить (400)", r.status_code == 400, f"{r.status_code} {r.text[:80]}")
    legacy_cnt_after = (await db_exec("select count(*) from categories where name_en='User items'"))[0][0]
    check("П.1", "служебная категория при этом не воссоздаётся", legacy_cnt_after == legacy_cnt_before, f"{legacy_cnt_before}->{legacy_cnt_after}")
    prod_rows = await db_exec("select count(*) from products where content_data->>'listing_id' = :l", l=str(legacy_listing))
    check("П.1", "товар в каталоге не создан", prod_rows[0][0] == 0)

    # ================================================================== П.17 уведомления на каждый проход
    head("П.17. Уведомление о проверке — каждый раз")
    r = await c.post(f"/api/p2p/seller/listings/{L1}/images", headers=S, files={"image": ("a.png", png(), "image/png")})
    check("П.17", "фото загружается", r.status_code == 200, r.text[:100])
    img1 = r.json()
    n0 = len(outbox())
    r = await c.post(f"/api/p2p/seller/listings/{L1}/submit", headers=S)
    check("П.17", "отправка на проверку", r.status_code == 200 and r.json() == {"status": "pending", "published": False}, r.text[:100])
    new = outbox()[n0:]
    check("П.17", "новая заявка: сообщение уходит обоим получателям админского чата",
          sorted(m["chat_id"] for m in new) == ["111", "222"] and all(m["text"].startswith("Новая заявка на размещение") for m in new), str(new)[:200])
    check("П.17", "в сообщении кнопки «Одобрить» и «Отклонить» с id заявки",
          all(L1 in json.dumps(m["reply_markup"]) and "mod:approve" in json.dumps(m["reply_markup"]) for m in new))

    r = await c.post(f"/api/admin/p2p/listings/{L1}/moderate", headers=M, json={"approve": True, "comment": "Все в порядке"})
    check("П.17", "модератор одобряет заявку", r.status_code == 200 and r.json()["status"] == "approved", r.text[:100])
    product_id = r.json().get("product_id")
    found = (await get_fresh("/api/products", params={"search": "Механическая клавиатура", "lang": "ru"})).json()
    check("П.17", "после одобрения товар в каталоге", any(p["id"] == product_id for p in found))
    check("П.17", "продавцу ушло уведомление об одобрении", any("одобрена" in m["text"] for m in outbox()))

    for round_no, new_name in ((1, "Клавиатура Keychron"), (2, "Клавиатура Keychron K2")):
        n0 = len(outbox())
        r = await c.patch(f"/api/p2p/seller/listings/{L1}", headers=S, json={"name": new_name})
        check("П.17", f"правка №{round_no} опубликованного товара: уходит на повторную проверку",
              r.status_code == 200 and r.json()["remoderating"] is True, r.text[:100])
        new = outbox()[n0:]
        check("П.17", f"правка №{round_no}: модераторам снова приходит уведомление (оба получателя)",
              sorted(m["chat_id"] for m in new) == ["111", "222"] and all(m["text"].startswith("Товар изменён и снова ждёт проверки") for m in new) and new_name in new[0]["text"],
              str(new)[:220])
        hidden = (await get_fresh("/api/products", params={"search": "Keychron", "lang": "ru"})).json()
        check("П.17", f"правка №{round_no}: до проверки товар снят с витрины", not any(p["id"] == product_id for p in hidden))
        r = await c.post(f"/api/admin/p2p/listings/{L1}/moderate", headers=M, json={"approve": True})
        check("П.17", f"правка №{round_no}: модератор снова публикует", r.status_code == 200)

    n0 = len(outbox())
    r = await c.patch(f"/api/p2p/seller/listings/{L1}", headers=S, json={"name": "Клавиатура Keychron K2"})
    check("П.17", "сохранение без изменений не создаёт заявку и уведомление", r.json()["remoderating"] is False and len(outbox()) == n0)

    n0 = len(outbox())
    r = await c.post(f"/api/p2p/seller/listings/{L1}/images", headers=S, files={"image": ("b.png", png(), "image/png")})
    new = outbox()[n0:]
    check("П.17", "новое фото у опубликованного товара тоже идёт на проверку с уведомлением",
          r.json().get("remoderating") is True and len(new) == 2 and new[0]["text"].startswith("Товар изменён"))
    await c.post(f"/api/admin/p2p/listings/{L1}/moderate", headers=M, json={"approve": True})

    # ================================================================== П.19 публикация без проверки
    head("П.19. Публикация без проверки для проверенных")
    r = await c.get("/api/admin/settings", headers=A)
    setting = next((x for x in r.json() if x["key"] == "p2p_auto_publish_verified"), None)
    check("П.19", "опция есть в настройках админки и по умолчанию выключена", setting and setting["value"] is False, str(setting)[:120])

    async def new_listing(headers, name, with_photo=True):
        r = await c.post("/api/p2p/seller/listings", headers=headers, json={**body, "name": name, "name_en": name, "category_id": category})
        lid = r.json()["id"]
        if with_photo:
            await c.post(f"/api/p2p/seller/listings/{lid}/images", headers=headers, files={"image": ("p.png", png(), "image/png")})
        return lid

    # выключено: проверенный продавец всё равно идёт к модератору
    r = await c.post(f"/api/admin/p2p/sellers/{profile_id}/verify", headers=A, json={"verified": True})
    check("П.19", "админ ставит галочку «проверенный»", r.status_code == 200 and r.json()["is_verified"] is True)
    L2 = await new_listing(S, "Проверка выключена Alpha")
    r = await c.post(f"/api/p2p/seller/listings/{L2}/submit", headers=S)
    check("П.19", "опция выключена: даже проверенный продавец идёт к модератору", r.json().get("published") is False and r.json()["status"] == "pending")
    await c.post(f"/api/admin/p2p/listings/{L2}/moderate", headers=M, json={"approve": False, "comment": "тест, сбрасываем"})

    r = await c.put("/api/admin/settings/p2p_auto_publish_verified", headers=A, json={"value": True})
    check("П.19", "админ включает опцию", r.status_code == 200 and r.json()["value"] is True)
    # у Alpha теперь REJECTED -> можно отправить снова
    n0 = len(outbox())
    r = await c.post(f"/api/p2p/seller/listings/{L2}/submit", headers=S)
    check("П.19", "включено: товар проверенного продавца публикуется без проверки", r.json().get("published") is True and r.json()["status"] == "approved", r.text[:100])
    pub = (await get_fresh("/api/products", params={"search": "Проверка выключена Alpha", "lang": "ru"})).json()
    check("П.19", "товар сразу виден в каталоге", len(pub) == 1)
    new = outbox()[n0:]
    check("П.19", "модераторам — сообщение для сведения без кнопок",
          len(new) == 2 and all(m["text"].startswith("Опубликовано без проверки") and m["reply_markup"] is None for m in new), str(new)[:200])
    n0 = len(outbox())
    r = await c.patch(f"/api/p2p/seller/listings/{L2}", headers=S, json={"name": "Проверка выключена Beta"})
    check("П.19", "правка проверенного: публикуется сразу, повторной проверки нет",
          r.json().get("published") is True and r.json()["remoderating"] is False, r.text[:100])
    pub = (await get_fresh("/api/products", params={"search": "Проверка выключена Beta", "lang": "ru"})).json()
    check("П.19", "после правки товар остаётся в каталоге с новым названием", len(pub) == 1)
    audit = (await c.get("/api/admin/staff/audit-log", headers=A, params={"action": "listing.auto_publish"})).json()
    check("П.19", "автопубликации записаны в журнал действий (actor — система)", audit["total"] >= 2 and audit["items"][0]["actor_role"] == "system", str(audit["total"]))

    other_id, O = await make_app_user("other")
    await c.post("/api/p2p/seller/register", headers=O, json={"display_name": f"OtherShop{random.randint(1000, 9999)}", "accept_terms": True})
    L3 = await new_listing(O, "Непроверенный продавец")
    r = await c.post(f"/api/p2p/seller/listings/{L3}/submit", headers=O)
    check("П.19", "продавец без галочки при включённой опции — по-прежнему к модератору", r.json().get("published") is False)

    await c.put("/api/admin/settings/p2p_auto_publish_verified", headers=A, json={"value": False})
    L4 = await new_listing(S, "Опция снова выключена")
    r = await c.post(f"/api/p2p/seller/listings/{L4}/submit", headers=S)
    check("П.19", "опцию выключили — снова только через модератора", r.json().get("published") is False)

    # ================================================================== П.6 отзывы за 30 дней
    head("П.6. Отзывы о продавцах — 30 дней")
    buyer_id, B = await make_app_user("buyer")
    old_reviews = [(5, 2), (3, 20), (1, 45), (2, 200)]
    for rating, days in old_reviews:
        await db_exec("insert into reviews (id, user_id, product_id, text, rating, is_hidden, is_fake, created_at) "
                      "values (gen_random_uuid(), :u, :p, :t, :r, false, false, now() - (:d || ' days')::interval)",
                      u=buyer_id, p=product_id, t=f"отзыв {days} дн назад", r=rating, d=str(days))
    store = (await get_fresh(f"/api/stores/seller/{profile_id}?lang=ru")).json()
    check("П.6", "магазин: в оценку входят только отзывы за 30 дней (2 из 4, среднее 4.0)",
          store["rating_count"] == 2 and store["rating"] == 4.0, f"{store['rating']} / {store['rating_count']}")
    shown = (await c.get("/api/reviews", params={"product_id": product_id})).json()
    check("П.6", "на странице товара — только отзывы за 30 дней", len(shown) == 2, str(len(shown)))
    page = (await get_fresh(f"/api/products/{product_id}", params={"lang": "ru"})).json()
    check("П.6", "карточка товара: оценка продавца считается по тому же окну",
          page.get("author_reviews") == 2 and page.get("author_rating") == 4.0, f"{page.get('author_rating')} / {page.get('author_reviews')}")
    allr = (await c.get("/api/reviews/admin/all", headers=A)).json()
    old_ids = [x for x in allr if str(x.get("product_id") or (x.get("product") or {}).get("id")) == product_id]
    if not old_ids:
        old_ids = [x for x in allr if str(x.get("text", "")).startswith("отзыв ")]
    check("П.6", "старые отзывы не удалены: админка видит все 4", len(old_ids) == 4, str(len(old_ids)))
    cabinet = (await c.get("/api/p2p/seller/me", headers=S)).json()
    check("П.6", "кабинет продавца показывает ту же оценку, что и витрина", cabinet["rating"] == 4.0 and cabinet["rating_count"] == 2)
    await c.put("/api/admin/settings/seller_reviews_window_days", headers=A, json={"value": 60})
    store60 = (await get_fresh(f"/api/stores/seller/{profile_id}?lang=ru")).json()
    check("П.6", "срок меняется в настройках: 60 дней → 3 отзыва", store60["rating_count"] == 3, str(store60["rating_count"]))
    await c.put("/api/admin/settings/seller_reviews_window_days", headers=A, json={"value": 0})
    store0 = (await get_fresh(f"/api/stores/seller/{profile_id}?lang=ru")).json()
    check("П.6", "0 — без ограничения: 4 отзыва", store0["rating_count"] == 4)
    await c.put("/api/admin/settings/seller_reviews_window_days", headers=A, json={"value": 30})
    row = await db_exec("select id from products where owner_user_id is null and type <> 'subscription' and is_active limit 1")
    if row:
        platform_product = row[0][0]
    else:
        platform_product = uuid.uuid4()
        await db_exec("insert into products (id, name_ru, name_en, description_ru, description_en, price_usdt, image_url, category_id, type, is_top, sort_order, is_active, is_p2p, content_data, images, created_at, min_quantity) "
                      "values (:i,'Товар площадки','Platform item','описание','description',5,'/uploads/products/placeholder.png',:c,'service',false,0,true,false,'{}','[]',now(),1)",
                      i=platform_product, c=uuid.UUID(category))
    await db_exec("insert into reviews (id, user_id, product_id, text, rating, is_hidden, is_fake, created_at) "
                  "values (gen_random_uuid(), :u, :p, 'старый отзыв площадке', 4, false, false, now() - interval '300 days')", u=buyer_id, p=platform_product)
    plat = (await c.get("/api/reviews", params={"product_id": str(platform_product)})).json()
    check("П.6", "отзывы на товары самой площадки окном не ограничиваются", any("старый отзыв площадке" == x["text"] for x in plat))

    # ================================================================== П.11 условия на двух языках
    head("П.11. Условия площадки на двух языках")
    r = await c.get("/api/admin/settings", headers=A)
    keys = {x["key"] for x in r.json()}
    check("П.11", "в настройках есть русский и английский тексты и общая версия", {"terms_text", "terms_text_en", "terms_version"} <= keys)
    await c.put("/api/admin/settings/terms_text", headers=A, json={"value": "Условия площадки (русский текст)"})
    await c.put("/api/admin/settings/terms_text_en", headers=A, json={"value": ""})
    en = (await get_fresh("/api/terms", params={"lang": "en"})).json()
    check("П.11", "английского текста нет → английскому пользователю русский, язык помечен ru", en["text"].startswith("Условия") and en["language"] == "ru")
    await c.put("/api/admin/settings/terms_text_en", headers=A, json={"value": "Platform terms (English text)"})
    ru = (await get_fresh("/api/terms", params={"lang": "ru"})).json()
    en = (await get_fresh("/api/terms", params={"lang": "en"})).json()
    de = (await get_fresh("/api/terms", params={"lang": "de"})).json()
    check("П.11", "ru → русский, en → английский, версия общая",
          ru["text"].startswith("Условия") and en["text"].startswith("Platform") and en["language"] == "en" and ru["version"] == en["version"])
    check("П.11", "неизвестный язык → русский", de["text"].startswith("Условия"))
    version = ru["version"]
    r = await c.post("/api/terms/accept", headers=B, json={"version": version})
    check("П.11", "принятие условий по версии работает", r.status_code == 200 and r.json()["accepted"] is True, r.text[:80])
    st = (await c.get("/api/terms/status", headers=B)).json()
    check("П.11", "после принятия статус «принято»", st["accepted"] is True)

    # ================================================================== вход через Telegram (настоящий путь)
    head("Вход в приложение через Telegram (подпись initData)")
    tg_id = random.randint(6_000_000_000, 6_900_000_000)
    r = await c.post("/api/auth/telegram", headers={"X-Telegram-Init-Data": init_data(BOT_TOKEN, tg_id)})
    check("вход", "подписанный initData принимается, выдаётся токен", r.status_code == 200 and "access_token" in r.json(), r.text[:100])
    app_token = {"Authorization": f"Bearer {r.json().get('access_token', '')}"}
    check("вход", "токен приложения работает (корзина пуста)", (await c.get("/api/cart", headers=app_token)).status_code == 200)
    bad = init_data(BOT_TOKEN, tg_id).replace("hash=", "hash=0")
    r = await c.post("/api/auth/telegram", headers={"X-Telegram-Init-Data": bad})
    check("вход", "initData с испорченной подписью отклоняется (401)", r.status_code == 401)
    r = await c.get("/api/admin/p2p/listings", headers=app_token)
    check("вход", "токен обычного пользователя не открывает админку (403)", r.status_code == 403)

    # ================================================================== П.18 удаление фото
    head("П.18. Удаление фото и аватарок модератором")
    r = await c.post("/api/p2p/seller/me/avatar", headers=S, files={"image": ("logo.png", png(400, 400), "image/png")})
    check("П.18", "продавец загружает логотип магазина", r.status_code == 200, r.text[:100])
    avatar = r.json().get("avatar_url") or (await c.get("/api/p2p/seller/me", headers=S)).json()["avatar_url"]
    r1 = await c.get(avatar)
    check("П.18", "логотип открывается по ссылке", r1.status_code == 200 and r1.headers["content-type"].startswith("image/"))
    time.sleep(0.5)
    r = await c.delete(f"/api/admin/p2p/sellers/{profile_id}/avatar", headers=M)
    check("П.18", "модератор удаляет логотип магазина", r.status_code == 200, r.text[:100])
    check("П.18", "файл удалён с диска (404), копии тоже",
          (await c.get(avatar)).status_code == 404 and (await c.get(avatar + "?size=thumb")).status_code == 404)
    check("П.18", "у магазина больше нет логотипа", (await c.get("/api/p2p/seller/me", headers=S)).json()["avatar_url"] is None)
    check("П.18", "продавцу ушло уведомление", any("удалил логотип" in m["text"] for m in outbox()))
    r = await c.delete(f"/api/admin/p2p/sellers/{profile_id}/avatar", headers=M)
    check("П.18", "повторное удаление — понятная ошибка, а не сбой", r.status_code == 400)

    listing = next(x for x in (await c.get("/api/p2p/seller/listings", headers=S)).json() if x["id"] == L1)
    photo_urls = [i["url"] for i in listing["images"]]
    photo_codes = [(await c.get(u)).status_code for u in photo_urls]
    check("П.18", "у опубликованного объявления есть фото", len(photo_urls) >= 2 and all(x == 200 for x in photo_codes), str(photo_codes))
    victim = listing["images"][0]
    r = await c.delete(f"/api/admin/p2p/listings/{L1}/images/{victim['id']}", headers=M)
    check("П.18", "модератор удаляет фото объявления", r.status_code == 200 and r.json()["remaining"] == len(photo_urls) - 1, r.text[:100])
    check("П.18", "файл фото удалён с диска", (await c.get(victim["url"])).status_code == 404)
    card = (await get_fresh(f"/api/products/{product_id}", params={"lang": "ru"})).json()
    check("П.18", "из карточки товара в каталоге фото тоже исчезло", victim["url"] not in card["images"] and card["image_url"] != victim["url"], str(card["images"]))
    rest_codes = [(await c.get(u)).status_code for u in photo_urls[1:]]
    check("П.18", "остальные фото на месте", all(x == 200 for x in rest_codes), str(rest_codes))
    r = await c.delete(f"/api/admin/p2p/listings/{L1}/images/{uuid.uuid4()}", headers=M)
    check("П.18", "несуществующее фото — 404", r.status_code == 404)

    # ================================================================== журнал действий
    head("П.13. Журнал действий модератора")
    # В копии есть и записи настоящего модератора клиента — смотрим только своего
    audit = (await c.get("/api/admin/staff/audit-log", headers=A, params={"actor_id": moderator_id, "limit": 100})).json()
    actions = {x["action"] for x in audit["items"]}
    check("П.13", "все решения модератора в журнале (одобрение, отказ, удаление фото)",
          {"listing.approve", "listing.reject", "photo.delete"} <= actions, str(sorted(actions)))
    check("П.13", "записи содержат кто/когда/что: имя, роль, объект, подробности",
          all(x["actor_name"] == MOD and x["created_at"] and x["target_id"] and x["details"] for x in audit["items"]))
    rej = next(x for x in audit["items"] if x["action"] == "listing.reject")
    check("П.13", "в записи об отказе — причина", rej["details"].get("comment") == "тест, сбрасываем", str(rej["details"]))
    by_role = (await c.get("/api/admin/staff/audit-log", headers=A, params={"role": "moderator", "limit": 200})).json()
    check("П.13", "журнал фильтруется по конкретному модератору и по роли",
          audit["total"] >= 6 and all(x["actor_id"] == moderator_id for x in audit["items"])
          and by_role["total"] >= audit["total"] and all(x["actor_role"] == "moderator" for x in by_role["items"]),
          f"{audit['total']} / {by_role['total']}")
    sys_rows = (await c.get("/api/admin/staff/audit-log", headers=A, params={"role": "system"})).json()
    check("П.13", "действия системы (автопубликация) отделены от людей", sys_rows["total"] >= 2)
    adm_rows = (await c.get("/api/admin/staff/audit-log", headers=A, params={"role": "admin"})).json()
    kinds = {x["action"] for x in adm_rows["items"]}
    check("П.13", "действия администратора тоже пишутся (настройки, галочка, модераторы)",
          {"settings.update", "seller.verify", "moderator.create"} <= kinds, str(sorted(kinds)))
    # в той же транзакции: откат действия не оставляет записи (проверено юнит-тестами) — здесь целостность
    ghost = await db_exec("select count(*) from admin_audit_log a where a.action='listing.approve' and not exists (select 1 from product_listings l where l.id::text = a.target_id)")
    check("П.13", "записей о действиях над несуществующими заявками нет", ghost[0][0] == 0)

    # ================================================================== П.15 защита: лимит, пароль, токены
    head("П.15. Защита админки: лимит попыток, смена пароля, сброс токенов")
    spoof = {"X-Forwarded-For": "198.51.100.77"}
    codes = []
    for _ in range(10):
        codes.append((await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": "wrong-password-xyz"}, headers=spoof)).status_code)
    check("П.15", "10 неверных паролей подряд — 401", codes == [401] * 10, str(codes))
    r = await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}, headers=spoof)
    check("П.15", "11-я попытка (даже с верным паролем) — 429, лимит на адрес", r.status_code == 429, str(r.status_code))
    for _ in range(15):
        await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": "wrong-password-xyz"}, headers=spoof)
    r = await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}, headers={"X-Forwarded-For": "198.51.100.88"})
    check("П.15", "с другого адреса вход открыт: лимит не общий на всех", r.status_code == 200)
    log = (await c.get("/api/admin/staff/login-log", headers=A, params={"limit": 200})).json()
    from_spoof = [x for x in log["items"] if x["ip"] == "198.51.100.77"]
    reasons = [x["reason"] for x in from_spoof]
    check("П.15", "журнал входов: 10 неверных паролей записаны, IP виден", reasons.count("bad_password") == 10, str(len(from_spoof)))
    check("П.15", "отказов по лимиту — одна запись, а не по записи на каждый запрос", reasons.count("rate_limited") == 1, str(reasons.count("rate_limited")))
    unknown = await c.post("/api/admin/auth/login", json={"username": "no_such_person", "password": "whatever-password"})
    log = (await c.get("/api/admin/staff/login-log", headers=A, params={"success": "false", "limit": 5})).json()
    check("П.15", "неизвестный логин тоже в журнале", unknown.status_code == 401 and log["items"][0]["reason"] == "unknown_user")
    check("П.15", "в журнале нет паролей", all("wrong-password" not in json.dumps(x) and ADMIN_PASS not in json.dumps(x) for x in log["items"]))

    # смена пароля администратором
    r = await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}, headers={"X-Forwarded-For": "203.0.113.11"})
    old_token = r.json()["access_token"]
    old_cookie = next(x for x in r.headers.get_list("set-cookie") if "admin_refresh_token" in x).split("admin_refresh_token=")[1].split(";")[0]
    OLD = {"Authorization": f"Bearer {old_token}"}
    for weak in ("short1", "aaaaaaaaaaaa", "x" * 80):
        r = await c.post("/api/admin/auth/change-password", headers=OLD, json={"current_password": ADMIN_PASS, "new_password": weak})
        check("П.15", f"слабый пароль отклонён ({weak[:12]}…)", r.status_code == 400, str(r.status_code))
    r = await c.post("/api/admin/auth/change-password", headers=OLD, json={"current_password": "not-my-password", "new_password": "Brand-New-Admin-Pass-9"})
    check("П.15", "смена пароля требует верный текущий", r.status_code == 400)
    r = await c.post("/api/admin/auth/change-password", headers=OLD, json={"current_password": ADMIN_PASS, "new_password": "Brand-New-Admin-Pass-9"})
    check("П.15", "пароль меняется", r.status_code == 200, r.text[:100])
    check("П.15", "сразу после смены старый токен не работает (выход из админки)", (await c.get("/api/admin/staff/moderators", headers=OLD)).status_code == 401)
    check("П.15", "и первый токен тоже", (await c.get("/api/admin/staff/moderators", headers=A)).status_code == 401)
    revoked_bad, revoked_n = [], 0
    for route in admin_only + staff_routes:
        if "GET" in route.methods and "{" not in route.path:
            for hdr in (OLD, A):
                resp = await c.get(route.path, headers=hdr)
                revoked_n += 1
                if resp.status_code != 401:
                    revoked_bad.append(f"{route.path} -> {resp.status_code}")
    check("П.15", f"после смены пароля оба старых токена закрыты во ВСЕХ разделах админки, включая статистику, пользователей и заказы ({revoked_n} запросов)",
          not revoked_bad and revoked_n >= 50, "; ".join(revoked_bad[:4]) or str(revoked_n))
    r = await c.post("/api/admin/auth/refresh", headers={"Cookie": f"admin_refresh_token={old_cookie}"})
    check("П.15", "старая refresh-кука больше не продлевает сессию", r.status_code == 401)
    r = await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}, headers={"X-Forwarded-For": "203.0.113.12"})
    check("П.15", "старый пароль из настроек сервера больше НЕ открывает вход", r.status_code == 401)
    r = await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": "Brand-New-Admin-Pass-9"}, headers={"X-Forwarded-For": "203.0.113.13"})
    check("П.15", "новый пароль работает", r.status_code == 200)
    A = {"Authorization": f"Bearer {r.json()['access_token']}"}
    new_cookie = next(x for x in r.headers.get_list("set-cookie") if "admin_refresh_token" in x).split("admin_refresh_token=")[1].split(";")[0]

    # выйти везде
    r2 = await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": "Brand-New-Admin-Pass-9"}, headers={"X-Forwarded-For": "203.0.113.14"})
    second = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    r = await c.post("/api/admin/auth/logout-all", headers=A)
    check("П.15", "«Выйти везде» выполнен", r.status_code == 200, r.text[:80])
    check("П.15", "после него не работают ни этот токен, ни токен с другого устройства",
          (await c.get("/api/admin/staff/moderators", headers=A)).status_code == 401 and (await c.get("/api/admin/staff/moderators", headers=second)).status_code == 401)
    r = await c.post("/api/admin/auth/refresh", headers={"Cookie": f"admin_refresh_token={new_cookie}"})
    check("П.15", "и refresh-куки отозваны", r.status_code == 401)
    r = await c.post("/api/admin/auth/login", json={"username": ADMIN_USER, "password": "Brand-New-Admin-Pass-9"}, headers={"X-Forwarded-For": "203.0.113.15"})
    A = {"Authorization": f"Bearer {r.json()['access_token']}"}
    check("П.15", "после «Выйти везде» вход заново возможен", r.status_code == 200)

    # токен, выданный до появления версий (старая сборка админки)
    from sqlalchemy import select  # noqa
    admin_uid = (await db_exec("select id from users where username = :u", u=ADMIN_USER))[0][0]
    legacy = create_access_token({"user_id": str(admin_uid), "sub": ADMIN_USER, "is_admin": True})
    tv = (await db_exec("select token_version from users where id = :i", i=admin_uid))[0][0]
    legacy_now = await c.get("/api/admin/staff/moderators", headers={"Authorization": f"Bearer {legacy}"})
    check("П.15", f"токен старого образца (без версии) приравнен к версии 0 и при версии {tv} не действует", legacy_now.status_code == 401 if tv else legacy_now.status_code == 200, str(legacy_now.status_code))

    # модератор: сброс пароля, приостановка, снятие
    r = await c.post("/api/admin/auth/login", json={"username": MOD, "password": "Moder-Pass-2026"})
    mod_token = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = await c.post(f"/api/admin/staff/moderators/{moderator_id}/password", headers=A, json={"password": "Moder-Pass-NEW-2026"})
    check("П.13–14", "админ задаёт модератору новый пароль", r.status_code == 200)
    check("П.13–14", "прежняя сессия модератора завершена", (await c.get("/api/admin/p2p/listings", headers=mod_token)).status_code == 401)
    check("П.13–14", "старый пароль модератора не подходит",
          (await c.post("/api/admin/auth/login", json={"username": MOD, "password": "Moder-Pass-2026"})).status_code == 401)
    r = await c.post("/api/admin/auth/login", json={"username": MOD, "password": "Moder-Pass-NEW-2026"})
    mod_token = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = await c.post(f"/api/admin/staff/moderators/{moderator_id}/active", headers=A, json={"active": False})
    check("П.13–14", "приостановка модератора", r.status_code == 200 and r.json()["active"] is False)
    check("П.13–14", "приостановленный: токен не работает мгновенно", (await c.get("/api/admin/p2p/listings", headers=mod_token)).status_code in (401, 403))
    r = await c.post("/api/admin/auth/login", json={"username": MOD, "password": "Moder-Pass-NEW-2026"})
    check("П.13–14", "приостановленный не может войти", r.status_code == 401)
    r = await c.post(f"/api/admin/staff/moderators/{moderator_id}/active", headers=A, json={"active": True})
    r = await c.post("/api/admin/auth/login", json={"username": MOD, "password": "Moder-Pass-NEW-2026"})
    check("П.13–14", "возвращённый модератор снова входит", r.status_code == 200)
    mod_token = {"Authorization": f"Bearer {r.json()['access_token']}"}
    listed = (await c.get("/api/admin/staff/moderators", headers=A)).json()
    check("П.13–14", "в списке модераторов: последний вход и число действий", listed[0]["last_login"] and listed[0]["actions"] >= 3, str(listed[0]))
    r = await c.delete(f"/api/admin/staff/moderators/{moderator_id}", headers=A)
    check("П.13–14", "администратор снимает роль модератора", r.status_code == 200)
    check("П.13–14", "его токен мгновенно перестал работать", (await c.get("/api/admin/p2p/listings", headers=mod_token)).status_code in (401, 403))
    check("П.13–14", "войти он больше не может",
          (await c.post("/api/admin/auth/login", json={"username": MOD, "password": "Moder-Pass-NEW-2026"})).status_code == 401)
    kept = await db_exec("select count(*) from users where id = :i", i=uuid.UUID(moderator_id))
    kept_audit = await db_exec("select count(*) from admin_audit_log where actor_id = :i", i=uuid.UUID(moderator_id))
    check("П.13–14", "учётка и его действия в журнале сохранились", kept[0][0] == 1 and kept_audit[0][0] >= 3)

    # ================================================================== П.16 оптимизация
    head("П.16. Оптимизация: каталог, фото, нагрузка")
    cat_ids = [r[0] for r in await db_exec("select id from categories where name_en <> 'User items' order by id")]
    await db_exec("""
        insert into products (id, name_ru, name_en, description_ru, description_en, price_usdt, image_url, category_id,
                              type, is_top, sort_order, is_active, is_p2p, content_data, images, created_at, min_quantity)
        select gen_random_uuid(), 'Нагрузка ' || g, 'Load ' || g, 'описание нагрузочного товара ' || g, 'load item description ' || g,
               (g % 90 + 1)::numeric, '/uploads/products/placeholder.png',
               (cast(:cats as uuid[]))[(g % :n) + 1],
               'service', (g % 97 = 0), 0, true, false, '{}', '[]', now() - (g || ' minutes')::interval, 1
        from generate_series(1, 5000) g""", cats=cat_ids, n=len(cat_ids))
    eligible = (await db_exec(
        "select count(*) from products where is_active and ((type <> 'digital' and (stock is null or stock > 0)) or "
        "(type = 'digital' and exists (select 1 from digital_items d where d.product_id = products.id and not d.is_sold and (d.order_id is null or d.reserved_until < now()))))"))[0][0]
    print(f"  в каталоге для покупателя: {eligible} товаров (добавлено 5000 нагрузочных)")

    seen, pages, times, sizes, skip, wrong_flag = [], 0, [], [], 0, 0
    while True:
        t = time.perf_counter()
        r = await c.get("/api/products", params={"skip": skip, "limit": 40, "lang": "ru"})
        times.append((time.perf_counter() - t) * 1000)
        sizes.append(len(r.content))
        items = r.json()
        seen += [p["id"] for p in items]
        pages += 1
        more = r.headers.get("x-has-more")
        if (more == "1") != (len(seen) < eligible):
            wrong_flag += 1
        if more != "1":
            break
        skip += 40
    check("П.16", f"постраничный обход отдаёт каждый товар ровно один раз ({len(seen)} из {eligible}, {pages} страниц)",
          len(seen) == len(set(seen)) == eligible, f"{len(seen)}/{len(set(seen))}/{eligible}")
    check("П.16", "признак «дальше есть» верен на каждой странице", wrong_flag == 0, str(wrong_flag))
    METRICS["catalog_walk"] = {"pages": pages, "p50_ms": round(pct(times, .5), 1), "p95_ms": round(pct(times, .95), 1),
                               "max_ms": round(max(times), 1), "avg_page_kb": round(statistics.mean(sizes) / 1024, 1)}
    avg_item = statistics.mean(sizes) / 40
    METRICS["old_behaviour_kb"] = round(avg_item * eligible / 1024)
    print(f"  страница из 40 товаров: p50={METRICS['catalog_walk']['p50_ms']} мс, p95={METRICS['catalog_walk']['p95_ms']} мс, "
          f"~{METRICS['catalog_walk']['avg_page_kb']} КБ; прежняя выдача целиком была бы ~{METRICS['old_behaviour_kb']} КБ")
    check("П.16", f"страница каталога при {eligible} товарах отвечает быстро (p95 < 300 мс)", pct(times, .95) < 300, f"{pct(times, .95):.0f} мс")
    first = (await c.get("/api/products", params={"limit": 5, "lang": "ru"})).json()
    check("П.16", "хиты идут первыми", all(p["is_top"] for p in first[:3]))
    over = await c.get("/api/products", params={"limit": 100000})
    check("П.16", "потолок размера страницы (100) не обойти параметром", len(over.json()) == 100)
    for term, label in (("Нагрузка 4999", "по названию"), ("load item description 123", "по описанию на английском")):
        t = time.perf_counter()
        found = (await get_fresh("/api/products", params={"search": term, "lang": "ru", "limit": 40})).json()
        ms = (time.perf_counter() - t) * 1000
        check("П.16", f"серверный поиск {label} находит товар среди {eligible}", len(found) >= 1, f"{ms:.0f} мс")
    pct_search = (await get_fresh("/api/products", params={"search": "%", "lang": "ru"})).json()
    check("П.16", "«%» в поиске — обычный символ, а не шаблон", len(pct_search) < eligible)
    trgm = await db_exec("select count(*) from pg_indexes where indexname like 'ix_products_%_trgm'")
    check("П.16", "триграммные индексы поиска созданы миграцией (расширение pg_trgm есть в образе postgres)", trgm[0][0] == 4, str(trgm[0][0]))
    search_ms = []
    for n in range(40):
        t0_ = time.perf_counter()
        rr = await get_fresh("/api/products", params={"search": f"Нагрузка {2000 + n * 37}", "lang": "ru", "limit": 40})
        search_ms.append((time.perf_counter() - t0_) * 1000)
        assert rr.status_code == 200 and len(rr.json()) >= 1
    METRICS["search_uncached"] = {"p50_ms": round(pct(search_ms, .5), 1), "p95_ms": round(pct(search_ms, .95), 1)}
    check("П.16", f"поиск мимо кеша по {eligible} товарам: p95 < 100 мс", pct(search_ms, .95) < 100, f"p50={pct(search_ms, .5):.0f} мс, p95={pct(search_ms, .95):.0f} мс")
    # На 5000 товарах последовательное чтение дешевле индекса, и планировщик справедливо выбирает его;
    # индексы окупаются на десятках тысяч — это проверено отдельно на 65 000 товаров (см. отчёт)
    idx = await db_exec("select indexname from pg_indexes where indexname in ('ix_products_catalog','ix_products_owner','ix_orders_user','ix_orders_status','ix_order_items_order','ix_order_items_product','ix_cart_items_user','ix_digital_items_product','ix_withdrawals_user','ix_withdrawals_status','ix_reviews_product','ix_deals_product','ix_admin_audit_created','ix_admin_login_log_created')")
    check("П.16", "все 14 индексов созданы в базе", len(idx) == 14, str(len(idx)))
    plan = await db_exec("explain analyze select id from products where is_active and category_id = (select id from categories limit 1) order by is_top desc, sort_order desc, created_at desc, id limit 41")
    plan_text = " ".join(x[0] for x in plan)
    print("  план запроса каталога:", plan_text[:160].replace("\n", " "))

    # --- фото: тяжёлый оригинал и лёгкие копии через nginx
    big = png(2000, 2000)
    t = time.perf_counter()
    lid = await new_listing(S, "Тяжёлое фото", with_photo=False)
    r = await c.post(f"/api/p2p/seller/listings/{lid}/images", headers=S, files={"image": ("big.png", big, "image/png")})
    up_ms = (time.perf_counter() - t) * 1000
    check("П.16", f"тяжёлый PNG ({len(big) // 1024} КБ) загружается", r.status_code == 200, f"{up_ms:.0f} мс")
    url = r.json()["url"]
    full = await c.get(url)
    thumb = await c.get(url + "?size=thumb")
    default_len = len(full.content)
    check("П.16", "по адресу оригинала отдаётся облегчённая копия для страницы товара",
          full.status_code == 200 and full.headers["content-type"] in ("image/jpeg", "image/webp") and default_len < len(big) / 4,
          f"{full.headers['content-type']} {default_len // 1024} КБ против {len(big) // 1024} КБ")
    check("П.16", "?size=thumb отдаёт ещё меньшую копию для каталога",
          thumb.status_code == 200 and len(thumb.content) < default_len, f"{len(thumb.content) // 1024} КБ")
    check("П.16", "картинки кешируются на 30 дней (immutable)", "max-age=2592000" in full.headers.get("cache-control", "") and "immutable" in full.headers.get("cache-control", ""))
    METRICS["image"] = {"original_kb": len(big) // 1024, "page_kb": default_len // 1024, "thumb_kb": len(thumb.content) // 1024}
    r = await c.post(f"/api/p2p/seller/listings/{lid}/images", headers=S, files={"image": ("huge.bin", b"\0" * (21 * 1024 * 1024), "image/png")})
    check("П.16", "файл больше 20 МБ отклоняется, сервер не падает", r.status_code in (400, 413), str(r.status_code))
    r = await c.post(f"/api/p2p/seller/listings/{lid}/images", headers=S, files={"image": ("fake.png", b"<svg onload=alert(1)>", "image/png")})
    check("П.16", "поддельное «изображение» (не картинка) отклоняется", r.status_code == 400, str(r.status_code))
    # --- статика
    html = await c.get("/")
    import re
    asset = re.search(r'/assets/[^"]+\.js', html.text)
    r = await c.get(asset.group(0)) if asset else None
    check("П.16", "код приложения кешируется на год (immutable)", r is not None and "max-age=31536000" in r.headers.get("cache-control", ""))
    check("П.16", "страница приложения без кеша (новая версия подхватывается)", html.headers.get("cache-control") == "no-cache")
    r = await c.get("/assets/does-not-exist-123.js")
    check("П.16", "несуществующий файл сборки — 404, а не страница в кеше", r.status_code == 404)
    check("П.16", "внутренний API бота снаружи закрыт", (await c.post("/api/internal/moderate-listing", json={})).status_code == 404)

    # --- микрокеш nginx
    head("П.16. Микрокеш публичных ответов (nginx)")
    q = {"limit": 40, "lang": "ru", "skip": 120}
    first = await c.get("/api/products", params=q)
    second = await c.get("/api/products", params=q)
    check("П.16", "первый запрос каталога идёт в бэкенд (MISS), повторный — из кеша (HIT)",
          first.headers.get("x-cache-status") in ("MISS", "EXPIRED", "UPDATING") and second.headers.get("x-cache-status") == "HIT",
          f"{first.headers.get('x-cache-status')} -> {second.headers.get('x-cache-status')}")
    check("П.16", "из кеша приходит тот же ответ и заголовок «есть ещё»",
          first.content == second.content and first.headers.get("x-has-more") == second.headers.get("x-has-more"))
    other_lang = await c.get("/api/products", params={**q, "lang": "en"})
    check("П.16", "язык в ключе кеша: английский ответ не подменяется русским", other_lang.content != second.content)
    await asyncio.sleep(4)
    third = await c.get("/api/products", params=q)
    check("П.16", "через 3 секунды ответ обновляется (кеш короткий)", third.headers.get("x-cache-status") in ("EXPIRED", "MISS", "UPDATING", "STALE"),
          third.headers.get("x-cache-status"))
    await c.put("/api/admin/settings/terms_text", headers=A, json={"value": "Условия: проверка свежести кеша"})
    stale = await c.get("/api/terms", params={"lang": "ru"})
    await asyncio.sleep(4.2)
    fresh_after = await c.get("/api/terms", params={"lang": "ru"})
    check("П.16", "правка настройки видна обычным пользователям не позже чем через ~4 секунды (кеш всего 3 с)",
          "свежести кеша" in fresh_after.json()["text"], fresh_after.headers.get("x-cache-status", "") + " / до: " + stale.headers.get("x-cache-status", ""))
    # Авторизованные запросы приложения тоже обслуживаются из кеша (ответ от пользователя не зависит)
    with_token = await c.get("/api/products", params=q, headers=S)
    check("П.16", "запрос приложения с токеном получает тот же публичный ответ", with_token.status_code == 200 and with_token.headers.get("x-cache-status") in ("HIT", "MISS", "EXPIRED", "UPDATING", "STALE"))
    # данные пользователя в кеш попасть не должны
    ua, UA = await make_app_user("cache_a")
    ub, UB = await make_app_user("cache_b")
    some_product = (await c.get("/api/products", params={"limit": 5, "lang": "ru"})).json()[0]["id"]
    r = await c.post("/api/cart", headers=UA, json={"product_id": some_product, "quantity": 1})
    check("П.16", "пользователь A кладёт товар в корзину", r.status_code == 200, r.text[:80])
    cart_a = await c.get("/api/cart", headers=UA)
    cart_b = await c.get("/api/cart", headers=UB)
    check("П.16", "корзина A не попадает в кеш и не видна пользователю B",
          len(cart_a.json()["items"]) == 1 and len(cart_b.json()["items"]) == 0 and "x-cache-status" not in cart_a.headers,
          f"A={len(cart_a.json()['items'])} B={len(cart_b.json()['items'])}")
    for path, hdr in (("/api/p2p/seller/me", S), ("/api/p2p/seller/listings", S), ("/api/terms/status", S)):
        r1 = await c.get(path, headers=hdr)
        check("П.16", f"{path}: не кешируется", "x-cache-status" not in r1.headers and r1.status_code == 200, str(r1.status_code))
    for path in ("/api/products/admin", "/api/categories/all", "/api/admin/staff/moderators"):
        r1 = await c.get(path, headers=A)
        check("П.16", f"{path}: админский адрес не кешируется", "x-cache-status" not in r1.headers, f"{r1.status_code}")
    admin_ref = await c.get("/api/categories", headers={"Referer": f"{BASE}/admin/categories"})
    check("П.16", "запросы из самой админки обходят кеш (видят свои правки сразу)", admin_ref.headers.get("x-cache-status") in ("BYPASS", "MISS"), admin_ref.headers.get("x-cache-status"))
    created_cat = await c.post("/api/categories", headers=A, json={"name_ru": "Свежая категория", "name_en": "Fresh category", "sort_order": 1})
    check("П.16", "создание категории (POST) через nginx не кешируется и проходит", created_cat.status_code in (200, 201), str(created_cat.status_code))
    idx_scans = (await db_exec("select coalesce(idx_scan,0) from pg_stat_user_indexes where indexrelname = 'ix_products_catalog_order'"))
    check("П.16", "запросы каталога реально идут по индексу порядка (счётчик обращений растёт)",
          idx_scans and idx_scans[0][0] > 50, str(idx_scans))

    # --- нагрузка
    head("П.16. Живые пользователи (предельные нагрузки — отдельным испытанием на k6)")
    categories = [x["id"] for x in (await c.get("/api/categories?lang=ru")).json()]
    product_ids = [p["id"] for p in (await c.get("/api/products", params={"limit": 100, "lang": "ru"})).json()]
    shopper_tokens = [(await make_app_user(f"load{i}"))[1] for i in range(20)]

    async def load_profile(label: str, users: int, seconds: int, think: tuple[float, float]) -> dict:
        lat: dict[str, list[float]] = {}
        errors: dict[str, int] = {}
        statuses: dict[int, int] = {}
        hits = {"HIT": 0, "other": 0}
        stop = time.time() + seconds
        limits = httpx.Limits(max_connections=users + 20, max_keepalive_connections=users + 20)
        async with httpx.AsyncClient(base_url=BASE, timeout=30, limits=limits) as lc:
            async def hit(name, path, **kw):
                t0_ = time.perf_counter()
                try:
                    resp = await lc.get(path, **kw)
                    ok = resp.status_code < 400
                    statuses[resp.status_code] = statuses.get(resp.status_code, 0) + 1
                    if resp.headers.get("x-cache-status") == "HIT":
                        hits["HIT"] += 1
                    elif "x-cache-status" in resp.headers:
                        hits["other"] += 1
                except Exception:
                    ok = False
                    statuses[0] = statuses.get(0, 0) + 1
                lat.setdefault(name, []).append((time.perf_counter() - t0_) * 1000)
                if not ok:
                    errors[name] = errors.get(name, 0) + 1

            async def user(i):
                rnd = random.Random(i)
                tok = shopper_tokens[i % len(shopper_tokens)]
                await asyncio.sleep(rnd.random() * min(seconds / 4, 5))
                while time.time() < stop:
                    roll = rnd.random()
                    if roll < 0.38:
                        await hit("каталог (страница)", "/api/products", params={"skip": rnd.randrange(0, 4900, 40), "limit": 40, "lang": "ru"}, headers=tok)
                    elif roll < 0.50:
                        await hit("каталог по категории", "/api/products", params={"category_id": rnd.choice(categories), "limit": 40, "lang": "ru"}, headers=tok)
                    elif roll < 0.58:
                        await hit("поиск", "/api/products", params={"search": f"Нагрузка {rnd.randrange(1, 5000)}", "lang": "ru"}, headers=tok)
                    elif roll < 0.68:
                        await hit("карточка товара", f"/api/products/{rnd.choice(product_ids)}", params={"lang": "ru"}, headers=tok)
                    elif roll < 0.75:
                        await hit("категории", "/api/categories", params={"lang": "ru"}, headers=tok)
                    elif roll < 0.81:
                        await hit("магазины", "/api/stores", headers=tok)
                    elif roll < 0.92:
                        await hit("корзина (личные данные)", "/api/cart", headers=tok)
                    elif roll < 0.96:
                        await hit("главная страница", "/")
                    else:
                        await hit("настройки", "/api/settings/public", headers=tok)
                    await asyncio.sleep(rnd.uniform(*think))

            t0_ = time.time()
            await asyncio.gather(*(user(i) for i in range(users)))
            took = time.time() - t0_

        total = sum(len(v) for v in lat.values())
        errs = sum(errors.values())
        allms = [x for v in lat.values() for x in v]
        out = {"users": users, "seconds": round(took), "requests": total, "rps": round(total / took), "errors": errs,
               "p50_ms": round(pct(allms, .5)), "p95_ms": round(pct(allms, .95)), "p99_ms": round(pct(allms, .99)),
               "max_ms": round(max(allms)), "statuses": statuses, "cache_hits": hits["HIT"],
               "by_endpoint": {k: {"n": len(v), "p50": round(pct(v, .5)), "p95": round(pct(v, .95)), "errors": errors.get(k, 0)} for k, v in sorted(lat.items())}}
        print(f"\n  [{label}] {users} пользователей, {out['seconds']} с: {total} запросов = {out['rps']}/с, ошибок {errs}, "
              f"из кеша nginx {hits['HIT']}")
        print(f"  задержка: p50={out['p50_ms']} мс, p95={out['p95_ms']} мс, p99={out['p99_ms']} мс, максимум {out['max_ms']} мс")
        for name, row in out["by_endpoint"].items():
            print(f"    {name:<26} n={row['n']:<6} p50={row['p50']:<5} p95={row['p95']:<5} ошибок={row['errors']}")
        return out

    realistic = await load_profile("живые пользователи", LOAD_USERS_REAL, LOAD_SECONDS, (1.5, 5.0))
    METRICS["load_realistic"] = realistic
    check("П.16", f"{LOAD_USERS_REAL} одновременных живых пользователей: ошибок нет", realistic["errors"] == 0, str(realistic["statuses"]))
    check("П.16", "живые пользователи: p95 задержки < 300 мс", realistic["p95_ms"] < 300, f"{realistic['p95_ms']} мс")
    check("П.16", "живые пользователи: p99 задержки < 1 с", realistic["p99_ms"] < 1000, f"{realistic['p99_ms']} мс")
    r = await c.get("/api/products", params={"limit": 40, "lang": "ru"})
    check("П.16", "после нагрузки сервис отвечает штатно", r.status_code == 200)
    r = await c.get("/api/p2p/seller/me", headers=S)
    check("П.16", "и личные запросы тоже (база и пул соединений не исчерпаны)", r.status_code == 200)

    # ================================================================== токен бота в логах
    head("Безопасность: токен бота не попадает в логи")
    # Публикация отзыва в канал идёт настоящим запросом к api.telegram.org с поддельным токеном стенда:
    # Telegram отвечает ошибкой, а httpx кладёт в её текст адрес запроса вместе с токеном.
    # Что попало в журнал контейнера, проверяет stage_run.sh (счётчики внизу вывода).
    fake = await c.post("/api/reviews/admin/fake", headers=A, json={
        "product_id": product_id, "fake_username": "Проверка", "text": "Проверка журналов", "rating": 5, "fake_quantity": 1})
    check("безопасность", "публикация в канал с ошибкой Telegram не роняет запрос", fake.status_code == 200, f"{fake.status_code} {fake.text[:80]}")
    await asyncio.sleep(1.5)

    # ================================================================== целостность данных
    head("Целостность данных после испытаний")
    after = {t: (await db_exec(f"select count(*) from {t}"))[0][0]
             for t in ("users", "orders", "deals", "reviews")}
    check("данные", "боевые заказы и сделки в копии не тронуты", after["orders"] == before["orders"] and after["deals"] == before["deals"], f"{before} -> {after}")
    orphan = await db_exec("select count(*) from product_listings l where l.status = 'approved' and not exists (select 1 from products p where p.id = l.product_id)")
    check("данные", "нет «одобренных» заявок без товара", orphan[0][0] == 0)
    dupes = await db_exec("select count(*) from (select telegram_id from users group by telegram_id having count(*) > 1) x")
    check("данные", "нет дублей пользователей", dupes[0][0] == 0)

    # ================================================================== итог
    passed = sum(1 for r in RESULTS if r[2])
    failed = [r for r in RESULTS if not r[2]]
    print(f"\n===== ИТОГ: {passed} из {len(RESULTS)} проверок пройдено, {len(failed)} не пройдено; {time.time() - t_start:.0f} с =====")
    for section, name, _, detail in failed:
        print(f"  НЕ ПРОЙДЕНО [{section}] {name}   {detail}")
    with open("/outbox/results.json", "w", encoding="utf-8") as fh:
        json.dump({"results": RESULTS, "metrics": METRICS}, fh, ensure_ascii=False, indent=1, default=str)
    await c.aclose()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
