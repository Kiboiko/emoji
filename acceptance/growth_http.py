"""Stages 2–3 and seller/auth regression through the isolated nginx stage.

Requires verify_up.sh. Only the copied DB and stage control file are mutated.
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import httpx
from acceptance import BASE, BOT_TOKEN, ADMIN_USER, ADMIN_PASS, check, db_exec, png, RESULTS
from captured_transport import install

CONTROLS = os.environ.get("MOCK_CONTROLS", "/outbox/mock-controls.json")
if os.environ.get("CAPTURE_EXTERNAL_API") != "1" or "@gram-verify-db:5432/verify" not in os.environ.get("DATABASE_URL", ""):
    raise RuntimeError("This destructive acceptance script requires the isolated gram-verify database")
install(os.environ["OUTBOX"], CONTROLS)


def controls(**data):
    path = Path(CONTROLS)
    pending = path.with_suffix(".next")
    pending.write_text(json.dumps(data), encoding="utf-8")
    pending.replace(path)


def signed(tg_id, token=BOT_TOKEN):
    fields = {"auth_date": str(int(time.time())), "query_id": "acceptance",
        "signature": "stage-ed25519-placeholder", "user": json.dumps({"id": tg_id,
        "first_name": "Acceptance", "username": f"verify{tg_id}", "language_code": "ru"}, separators=(",", ":"))}
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urlencode(fields)}


async def main():
    controls()
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        async def request(method, path, *, expect=200, **kwargs):
            response = await c.request(method, path, **kwargs)
            check("HTTP 1–3", f"{method} {path}", response.status_code == expect, str(response.status_code))
            if response.status_code != expect:
                raise AssertionError(f"{method} {path}: {response.status_code} {response.text[:180]}")
            return response.json()

        async def app_user():
            tg = 8_000_000_000 + uuid.uuid4().int % 1_000_000_000
            data = await request("POST", "/api/auth/telegram", headers=signed(tg))
            return data["user"], {"Authorization": "Bearer " + data["access_token"]}, tg

        admin = await request("POST", "/api/admin/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        A = {"Authorization": "Bearer " + admin["access_token"]}
        refresh_cookie = c.cookies.get("admin_refresh_token")
        if not refresh_cookie:
            raise AssertionError("Admin refresh cookie missing")
        await request("GET", "/api/admin/publications", expect=401, headers={"Authorization":"Bearer "+refresh_cookie})
        bad = await c.post("/api/auth/telegram", headers=signed(8_999_999_999, "wrong-bot"))
        check("auth", "чужой токен бота не проходит", bad.status_code == 401)
        same_id = 9_000_000_000 + uuid.uuid4().int % 1_000_000_000
        concurrent = await asyncio.gather(*(c.post("/api/auth/telegram", headers=signed(same_id)) for _ in range(8)))
        check("auth", "8 одновременных первых входов без 500", all(r.status_code == 200 for r in concurrent), str([r.status_code for r in concurrent]))
        count = await db_exec("select count(*) from users where telegram_id=:tg", tg=same_id)
        check("auth", "одна запись пользователя при одновременном входе", count[0][0] == 1)
        seller, S, _ = await app_user()
        name = "Magazin " + uuid.uuid4().hex[:8]
        await request("POST", "/api/p2p/seller/register", headers=S, json={"display_name":name,"accept_terms":True})
        profile = await request("GET", "/api/p2p/seller/me", headers=S)
        check("маркет", "транслитерация принимается, название сохранено", profile["display_name"] == name)
        await request("POST", "/api/p2p/seller/register", headers=S, expect=400, json={"display_name":name,"accept_terms":True})
        other, O, _ = await app_user()
        races = await asyncio.gather(*(c.post("/api/p2p/seller/register", headers=O,
            json={"display_name":"Kupi_"+uuid.uuid4().hex[:8],"accept_terms":True}) for _ in range(2)))
        check("маркет", "одновременная регистрация одного продавца не даёт 500", sorted(r.status_code for r in races) in ([200,400],[200,409]), str([r.status_code for r in races]))
        for stem in ["Kupi_Tut", "Dobryi-Magazin", "Ya Prodavets"]:
            _, H, _ = await app_user()
            await request("POST", "/api/p2p/seller/register", headers=H, json={"display_name":stem+uuid.uuid4().hex[:3],"accept_terms":True})
        category = await request("POST", "/api/categories", headers=A, json={"name_ru":"Проверка "+uuid.uuid4().hex[:6],"name_en":"Verification"})
        child = await request("POST", "/api/categories", headers=A, json={"name_ru":"Подкатегория","name_en":"Subcategory","parent_id":category["id"]})
        await request("POST", "/api/categories", headers=A, expect=422, json={"name_ru":"Третий уровень","name_en":"Too deep","parent_id":child["id"]})
        draft = await request("POST", "/api/p2p/seller/listings", headers=S, json={"name":"Сквозной товар","name_en":"End-to-end item",
            "description":"Проверка всех этапов","description_en":"Verification","price_usd":"10.00","quantity":5,"category_id":child["id"],"accept_terms":True})
        await request("POST", f"/api/p2p/seller/listings/{draft['id']}/images", headers=S, files={"image":("test.png",png(noise=False),"image/png")})
        await request("POST", f"/api/p2p/seller/listings/{draft['id']}/submit", headers=S)
        approved = await request("POST", f"/api/admin/p2p/listings/{draft['id']}/moderate", headers=A, json={"approve":True})
        product_id = approved["product_id"]
        for sort in ["default","price_asc","price_desc","rating","sales"]:
            data = await request("GET", "/api/products", params={"category_id":category["id"],"sort":sort})
            check("каталог", f"подкатегория включена в родителя при {sort}", any(p["id"] == product_id for p in data))
        await request("PATCH", f"/api/admin/market-rankings/sellers/{profile['id']}", headers=A, json={"ranking_enabled":True})
        await request("POST", "/api/admin/market-rankings/refresh", headers=A)
        await request("PUT", "/api/admin/publications/config", headers=A, json={"enabled":True,"min_nano":1,"chat_id":-100123})
        # Payment responses come only from the captured indexer, never client assertions.
        invoice = await request("POST", f"/api/promotions/products/{product_id}/invoice", headers=S)
        check("продвижение", "повтор возвращает тот же счёт", (await request("POST", f"/api/promotions/products/{product_id}/invoice", headers=S))["id"] == invoice["id"])
        check("продвижение", "до индексера не оплачено", not (await request("GET", f"/api/promotions/{invoice['id']}/check", headers=S))["paid"])

        def tx(payment, label):
            return {"transaction_id":{"hash":label+uuid.uuid4().hex,"lt":"1"},"utime":int(time.time()),
                "in_msg":{"source":"stage-sender","value":payment["amount_nano"],"message":payment["comment"]}}
        transfers = [tx(invoice["payment"], "promotion-")]
        controls(transactions=transfers)
        promoted = await request("GET", f"/api/promotions/{invoice['id']}/check", headers=S)
        check("продвижение", "индексер подтверждает продвижение", promoted["paid"])
        check("продвижение", "повтор не продлевает срок", (await request("GET", f"/api/promotions/{invoice['id']}/check", headers=S))["promoted_until"] == promoted["promoted_until"])
        buyer, B, tg = await app_user()
        await request("POST", "/api/cart", headers=B, json={"product_id":product_id,"quantity":1})
        order = await request("POST", "/api/orders", headers=B, json={"currency":"TON","accept_terms":True})
        check("оплата", "кошелёк ещё не означает оплату", not (await request("GET", f"/api/payments/check/{order['order_id']}", headers=B))["paid"])
        transfers.append(tx(order["payment"], "order-"));controls(transactions=transfers)
        check("оплата", "подтверждение через индексер", (await request("GET", f"/api/payments/check/{order['order_id']}", headers=B))["paid"])
        deals = await request("GET", "/api/p2p/deals", headers=B)
        deal = next(d for d in deals if d["order_id"] == order["order_id"])
        await request("POST", f"/api/p2p/deals/{deal['id']}/delivered", headers=S)
        controls(transactions=transfers, send_errors={"sendPhoto":"timeout","sendMessage":"timeout"})
        await request("POST", f"/api/p2p/deals/{deal['id']}/confirm", headers=B)
        from services.telegram_publication_service import dispatch_one
        await dispatch_one()
        history = await request("GET", "/api/admin/publications", headers=A)
        post = history[0]
        check("публикации", "timeout даёт unknown после RELEASED", post["status"] == "unknown")
        controls(transactions=transfers)
        await dispatch_one()
        check("публикации", "unknown не повторяется автоматически", (await request("GET", "/api/admin/publications", headers=A))[0]["status"] == "unknown")
        await request("POST", f"/api/admin/publications/{post['id']}/resolve", headers=A, json={"action":"confirmed_sent","message_id":777})
        await request("PUT", "/api/admin/publications/config", headers=A, json={"enabled":False,"min_nano":1,"chat_id":-100123})
        await request("POST", "/api/reviews", headers=B, json={"product_id":product_id,"order_id":order["order_id"],"text":"Всё получено","rating":5})
        await request("POST", "/api/admin/market-rankings/refresh", headers=A)
        public = await request("GET", "/api/market-rankings/current")
        check("рейтинг", "продажа и отзыв попадают в рейтинг без финансовой утечки", any(r["id"] == profile["id"] for r in public["items"]) and all("volume_cents" not in r and "score" not in r for r in public["items"]))
        private = await request("GET", "/api/admin/market-rankings", headers=A)
        check("рейтинг", "оборот учитывается в USD-центах", next(r for r in private["ranking"]["items"] if r["id"]==profile["id"])["volume_cents"]==1000)
        feed = await request("GET", "/api/sales-feed")
        check("лента", "завершённый товар в ленте", any(p["product_id"]==product_id for p in feed["items"]))
        now = datetime.now(timezone.utc)
        gift = await request("POST", "/api/admin/giveaways", headers=A, json={"title_ru":"Проверка подарка","title_en":"Gift verification","prize":"NFT (stage only)",
            "start_at":(now-timedelta(hours=1)).isoformat(),"end_at":(now+timedelta(hours=1)).isoformat(),"requirements":[{"chat_id":-100123,"title":"Test","join_link":"https://t.me/stage"}]})
        gid = gift["id"]
        await request("GET", f"/api/giveaways/{gid}", expect=404)
        await request("POST", f"/api/admin/giveaways/{gid}/publish", headers=A)
        controls(transactions=transfers, memberships={f"-100123:{tg}":"left"})
        check("розыгрыш", "без подписки заявка не принята", not (await request("POST", f"/api/giveaways/{gid}/join", headers=B))["joined"])
        await db_exec("update giveaway_entries set checked_at=checked_at-interval '11 seconds' where giveaway_id=:id", id=uuid.UUID(gid))
        controls(transactions=transfers)
        check("розыгрыш", "подписка подтверждена сервером", (await request("POST", f"/api/giveaways/{gid}/join", headers=B))["joined"])
        await request("POST", f"/api/giveaways/{gid}/join", headers=B)
        await db_exec("update giveaways set end_at=(now() at time zone 'UTC')-interval '1 millisecond' where id=:id", id=uuid.UUID(gid))
        from services.giveaway_service import draw_one
        controls(transactions=transfers, deny_bot_admin=True)
        await draw_one(uuid.UUID(gid))
        check("розыгрыш", "потеря прав бота сохраняет кандидата", (await request("GET", f"/api/giveaways/{gid}"))["status"] == "waiting_for_telegram")
        controls(transactions=transfers)
        await db_exec("update giveaways set lease_until=null where id=:id", id=uuid.UUID(gid))
        await draw_one(uuid.UUID(gid));await draw_one(uuid.UUID(gid))
        result = await request("GET", f"/api/giveaways/{gid}")
        check("розыгрыш", "один победитель, нет утечки ID", result["status"]=="finished" and bool(result["winner"]) and "winner_user_id" not in result)
        check("розыгрыш", "победитель видит свой результат", (await request("GET", f"/api/giveaways/{gid}/my-entry", headers=B))["is_winner"])
        await request("POST", f"/api/admin/giveaways/{gid}/fulfilled", headers=A)
        attempts = await request("GET", f"/api/admin/giveaways/{gid}/draw-attempts", headers=A)
        check("розыгрыш", "сбой не выбрал другого кандидата", len(attempts)==1 and attempts[0]["status"]=="eligible")
        await request("GET", "/api/admin/publications", headers=B, expect=403)
        await request("GET", f"/api/admin/giveaways/{gid}/participants", headers=B, expect=403)
        from database import AsyncSessionLocal
        from services.finance_service import reconcile
        async with AsyncSessionLocal() as db:
            check("ledger", "проводки после оплаты/escrow/продвижения сходятся", (await reconcile(db)).ok)
    failed = [r for r in RESULTS if not r[2]]
    Path("/outbox/growth-results.json").write_text(json.dumps({"passed":len(RESULTS)-len(failed),"total":len(RESULTS),"failed":failed},ensure_ascii=False),encoding="utf-8")
    print(f"GROWTH TOTAL: {len(RESULTS)-len(failed)}/{len(RESULTS)} passed",flush=True)
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
