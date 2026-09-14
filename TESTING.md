# Инструкция по тестированию

Что сделано на этапах 0–4 и как это проверить. Проверено на Windows + Docker Desktop, команды одинаковы для Linux.

---

# 1. Что понадобится

## 1.1. Обязательно

| Что | Где взять | Зачем |
|---|---|---|
| **Docker + Compose v2** | Docker Desktop | Весь проект поднимается одной командой |
| **Токен тестового бота** | [@BotFather](https://t.me/BotFather) → `/newbot` | Вход в Mini App, уведомления, выдача доступа в каналы |

> **Заведите отдельного тестового бота, не боевой.** Боевой и локальный бот не могут читать апдейты Telegram одновременно — один будет перебивать другого.

## 1.2. Для проверки оплаты в TON

| Что | Где взять | Зачем |
|---|---|---|
| **Кошелёк в testnet** | Tonkeeper → Настройки → включить **Testnet**. Адрес → `TON_RECEIVING_ADDRESS` | Приём платежей платформой |
| **Тестовые монеты** | [@testgiver_ton_bot](https://t.me/testgiver_ton_bot) | Оплатить тестовый заказ |
| **Второй кошелёк** | Тот же Tonkeeper или другое устройство | Покупатель платит со своего кошелька |
| **Ключ toncenter** | [@tonapibot](https://t.me/tonapibot) → `/get_access_token`, выбрать **testnet** | Без ключа лимит ~1 запрос/сек. Для проверки хватит и без него, но будет медленно |

## 1.3. Для проверки подписок

| Что | Как сделать | Зачем |
|---|---|---|
| **Закрытый тестовый канал** | Telegram → Создать канал → тип **Частный** | Продажа доступа |
| **Бот — админ канала** | Канал → Управление → Администраторы → добавить бота | **Обязательно** права «Пригласительные ссылки» и «Блокировка участников» |
| **Второй аккаунт Telegram** | Любой | Покупатель. Со своего аккаунта-владельца канала подписку нормально не проверить |

> Без прав администратора бот физически не может ни выдать доступ, ни отозвать его. Канал без подтверждённых прав система **не даст опубликовать** — это защита, а не ошибка.

## 1.4. Для полного прогона Mini App (опционально)

| Что | Зачем |
|---|---|
| **HTTPS-домен или туннель** | Telegram Mini App и кошельки TON Connect не работают с `localhost` |

`ngrok` и `cloudflared` уже установлены на вашей машине — см. раздел 5.

---

# 2. Что можно проверить локально, а что нет

Честная картина, чтобы не тратить время впустую.

| Что | localhost | Туннель / сервер | Почему |
|---|---|---|---|
| Админ-панель целиком | **да** | да | Обычное веб-приложение |
| API (curl / Swagger) | **да** | да | — |
| Витрина в браузере | **да** | да | Включён dev-вход (`VITE_DEV_AUTH=true`) |
| Миграции, финансы, сверка | **да** | да | — |
| Автотесты (66 шт.) | **да** | да | — |
| Бот: `/start`, уведомления | **да** | да | Long polling — исходящие запросы, входящий доступ не нужен |
| **Подписки: выдача и отзыв доступа** | **да** | да | Вызовы Bot API исходящие, работают с локалки |
| Создание заказа и счёта в TON | **да** | да | — |
| Проверка транзакции в блокчейне | **да** | да | Опрос индексера исходящий |
| **Оплата кошельком (TON Connect)** | **нет** | да | Кошелёк сам скачивает `tonconnect-manifest.json` и сверяет origin — до `localhost` он не достучится |
| **Открытие Mini App кнопкой в боте** | **нет** | да | Telegram требует HTTPS |

**Вывод:** почти всё, включая подписки, проверяется на локалке. Туннель нужен только для двух вещей — подписи транзакции кошельком и открытия витрины кнопкой в боте.

---

# 3. Быстрый старт

## 3.1. Настроить `.env`

```bash
cp .env.example .env
```

Минимум для запуска:

```ini
DB_PASSWORD=любой_пароль
SECRET_KEY=длинная_случайная_строка
ADMIN_PASSWORD=пароль_админки

DEBUG=true              # локально: включает /api/auth/dev
COOKIE_SECURE=false     # локально по HTTP, иначе вход в админку не работает
VITE_DEV_AUTH=true      # витрина открывается в браузере без Telegram

TELEGRAM_BOT_TOKEN=токен_от_BotFather
VITE_BOT_USERNAME=имя_вашего_бота_без_собаки
ADMIN_CHAT_ID=ваш_telegram_id   # сюда придут алерты

INTERNAL_API_TOKEN=случайная_строка

TON_NETWORK=testnet
TON_RECEIVING_ADDRESS=адрес_вашего_testnet_кошелька
TON_API_KEY=ключ_от_tonapibot
```

Сгенерировать секреты:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Свой Telegram ID — у [@userinfobot](https://t.me/userinfobot).

> На боевом сервере `DEBUG`, `VITE_DEV_AUTH` — **`false`**, `COOKIE_SECURE` — **`true`**.

## 3.2. Запустить

```bash
docker compose up -d postgres
docker compose run --rm backend alembic upgrade head    # обязательно до первого старта
docker compose up -d
docker compose exec backend python seed.py              # демо-товары
```

Если меняли `.env` для фронта (`VITE_*`, `SITE_URL`) — пересобрать:

```bash
docker compose build frontend admin && docker compose up -d --force-recreate frontend admin
```

## 3.3. Проверить, что поднялось

```bash
docker compose ps
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/health
```

Все пять контейнеров — `Up`, `nginx`/`backend`/`postgres` — `healthy`.

| Адрес | Что |
|---|---|
| http://localhost:8080/ | Витрина |
| http://localhost:8080/admin/ | Админка (`admin` + `ADMIN_PASSWORD`) |
| http://localhost:8000/docs | Swagger, все эндпоинты |
| `localhost:5433` | PostgreSQL |

Пароль админки, если забыли: `grep ADMIN_PASSWORD .env`

---

# 4. Сценарии тестирования

## 4.0. Автотесты

```bash
docker compose exec postgres psql -U marketplace_user -d postgres -c "CREATE DATABASE marketplace_test;"
docker compose exec backend python -m pytest -q
```

Ожидаемо: **66 passed**.

---

## 4.1. Безопасность (этап 0)

### Служебный вход в админку закрыт на проде

```bash
# Временно ставим прод-режим
sed -i 's/^DEBUG=true/DEBUG=false/' .env
docker compose up -d --force-recreate backend && sleep 10

curl -s -w " -> HTTP %{http_code}\n" -X POST http://localhost:8080/api/auth/dev
# Ожидается: 404 (роут не существует, а не «403 но существует»)

sed -i 's/^DEBUG=false/DEBUG=true/' .env
docker compose up -d --force-recreate backend
```

**Было:** `DEBUG` по умолчанию `True`, в `.env` не задан → на проде любой мог получить админский токен **без пароля**.

### Перебор пароля админки

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code} " -X POST http://localhost:8080/api/admin/auth/login \
    -H "Content-Type: application/json" -d '{"username":"admin","password":"wrong"}'
done; echo
```

Ожидается: несколько `401`, затем `429`.

### Регистрация нового пользователя

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8080/api/auth/dev
```

Ожидается `200`. **Было:** падало с 500 — колонка `users.is_blocked` была `NOT NULL` без значения по умолчанию, а в модели отсутствовала. Регистрация не работала вообще.

---

## 4.2. Миграции (этап 1)

```bash
# Схема с нуля воспроизводится полностью
docker compose exec postgres psql -U marketplace_user -d postgres -c "CREATE DATABASE mp_check;"
docker compose exec -e DATABASE_URL="postgresql+asyncpg://marketplace_user:$(grep '^DB_PASSWORD=' .env | cut -d= -f2-)@postgres:5432/mp_check" \
  backend alembic upgrade head
docker compose exec postgres psql -U marketplace_user -d mp_check -c "\dt"
# Ожидается 19 таблиц

# autogenerate не предлагает деструктива
docker compose exec backend alembic revision --autogenerate -m "check"
# В созданном файле upgrade() должен содержать только pass
rm backend/alembic/versions/*check.py
docker compose exec postgres psql -U marketplace_user -d postgres -c "DROP DATABASE mp_check;"
```

Приложение **не стартует** на неактуальной схеме — это сделано намеренно, проверяется само при обычном запуске.

---

## 4.3. Финансы (этап 2)

```bash
ADMPASS=$(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2-)
ATOK=$(curl -s -X POST http://localhost:8080/api/admin/auth/login -H "Content-Type: application/json" \
  -d "{\"username\":\"admin\",\"password\":\"$ADMPASS\"}" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
UTOK=$(curl -s -X POST http://localhost:8080/api/auth/dev | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

### Настройки меняются без передеплоя

```bash
curl -s http://localhost:8080/api/admin/settings -H "Authorization: Bearer $ATOK" | python -m json.tool | head -30

# Поменять комиссию на 5%
curl -s -X PUT http://localhost:8080/api/admin/settings/commission_subscription_bp \
  -H "Authorization: Bearer $ATOK" -H "Content-Type: application/json" -d '{"value": 500}'

# Невалидное значение отбивается
curl -s -X PUT http://localhost:8080/api/admin/settings/referral_l1_bp \
  -H "Authorization: Bearer $ATOK" -H "Content-Type: application/json" -d '{"value": 20000}'
# Ожидается 400 с текстом «максимум 10000»
```

### Заявка на вывод замораживает деньги

```bash
# Начислить тестовый баланс
docker compose exec postgres psql -U marketplace_user -d marketplace \
  -c "UPDATE users SET referral_earnings = 50 WHERE username='dev_user';"
```

Дальше в админке (**Выводы**) или через API: подать заявку на 20, убедиться что баланс показывает 30, подтвердить вывод, убедиться что стало 30 и заморозка снялась. **Нажать «подтвердить» дважды** — сумма не должна списаться повторно.

### Сверка

```bash
curl -s -X POST http://localhost:8080/api/admin/finance/reconcile -H "Authorization: Bearer $ATOK" | python -m json.tool
```

Ожидается `"ok": true` и суммы по валютам **ровно 0**. Это главный инвариант: сумма всех проводок обязана быть нулём.

```bash
# Журнал: из чего сложился баланс
curl -s "http://localhost:8080/api/admin/finance/ledger?limit=20" -H "Authorization: Bearer $ATOK" | python -m json.tool
```

---

## 4.4. Оплата в TON (этап 3)

### Счёт выставляется (локально)

```bash
PID=$(curl -s http://localhost:8080/api/products | python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
curl -s -X POST http://localhost:8080/api/cart -H "Authorization: Bearer $UTOK" \
  -H "Content-Type: application/json" -d "{\"product_id\":\"$PID\",\"quantity\":1000}"

curl -s -X POST http://localhost:8080/api/orders -H "Authorization: Bearer $UTOK" \
  -H "Content-Type: application/json" -d '{"currency":"TON"}' | python -m json.tool
```

Проверить в ответе: `order_id`, сумма в USD, `amount_nano`, уникальный `comment` вида `MP-XXXXXXXX`, живой курс.

**Положите в корзину 2–3 разных товара** и убедитесь, что создаётся **один** заказ, а не три. Раньше на каждую позицию создавался отдельный заказ со своим счётом, а фронт открывал только первый.

```bash
docker compose exec postgres psql -U marketplace_user -d marketplace \
  -c "SELECT (SELECT count(*) FROM orders) o, (SELECT count(*) FROM order_items) i, (SELECT count(*) FROM payments) p;"
```

### Статус оплаты

```bash
OID=<order_id из ответа>
curl -s "http://localhost:8080/api/payments/check/$OID" -H "Authorization: Bearer $UTOK"
# Ожидается {"status":"pending","paid":false} — запрос реально ходит в блокчейн
```

### Реальная оплата — только через туннель или сервер

См. раздел 5. Сценарий:

1. Открыть витрину в Telegram, набрать корзину, «Оформить заказ».
2. Подключить кошелёк (Tonkeeper в режиме testnet).
3. Нажать «Оплатить», подписать транзакцию.
4. В течение ~15 секунд заказ переходит в оплаченный, товар приходит в бот.

**Что проверить отдельно:**

| Сценарий | Ожидаемо |
|---|---|
| Отказаться от подписи в кошельке | Возврат на экран оплаты без ошибки |
| Оплатить **меньше** нужного (вручную из кошелька, с тем же комментарием) | Товар **не** выдан, статус `underpaid`, вам в Telegram приходит алерт |
| Оплатить **больше** | Товар выдан, переплата в логах |
| Отправить тот же перевод дважды | Товар выдан один раз |
| Не платить 30 минут | Заказ отменяется, товар возвращается в сток |

Логи оплаты:

```bash
docker compose logs -f backend | grep -E "\[PAY\]|\[TON\]"
```

---

## 4.5. Подписки (этап 4)

Это **можно полностью проверить локально** — Bot API работает исходящими запросами.

### Подготовка

1. Создать **частный** канал в Telegram.
2. Добавить туда бота администратором с правами **«Пригласительные ссылки»** и **«Блокировка участников»**.
3. Узнать `chat_id` канала: переслать любой пост из него [@userinfobot](https://t.me/userinfobot), либо использовать `@username`, если канал публичный.

### Подключение канала

Через API (или в витрине, когда появится UI автора):

```bash
curl -s -X POST http://localhost:8080/api/subscriptions/author/channels \
  -H "Authorization: Bearer $UTOK" -H "Content-Type: application/json" \
  -d '{"chat_identifier":"-1001234567890","payout_wallet":"EQваш_кошелёк","accept_terms":true}' | python -m json.tool
```

**Проверить негативный сценарий:** убрать бота из админов канала и нажать проверку — `bot_is_admin: false` с понятной причиной. Попытка отправить канал на модерацию должна отбиться с 400.

```bash
CH=<channel_id>
curl -s -X POST "http://localhost:8080/api/subscriptions/author/channels/$CH/verify" -H "Authorization: Bearer $UTOK"
```

### Тариф и публикация

```bash
curl -s -X POST "http://localhost:8080/api/subscriptions/author/channels/$CH/plans" \
  -H "Authorization: Bearer $UTOK" -H "Content-Type: application/json" \
  -d '{"title_ru":"Месяц","title_en":"Month","duration_days":30,"price_usd":"5.00"}'

curl -s -X POST "http://localhost:8080/api/subscriptions/author/channels/$CH/submit" -H "Authorization: Bearer $UTOK"

# Одобрить как админ
curl -s -X POST "http://localhost:8080/api/admin/subscriptions/channels/$CH/moderate" \
  -H "Authorization: Bearer $ATOK" -H "Content-Type: application/json" -d '{"approve":true}'
```

После одобрения тариф появляется в каталоге товаров как обычный товар — подписка продаётся через ту же корзину и оплату.

### Покупка и выдача доступа

Купить подписку **со второго аккаунта** (владелец канала не годится — он уже в канале).

После оплаты:

1. В бот приходит **одноразовая ссылка**, действует сутки.
2. Переход по ссылке → пользователь в канале.
3. В админке подписка со статусом `active` и датой окончания.

```bash
curl -s "http://localhost:8080/api/admin/subscriptions?status=active" -H "Authorization: Bearer $ATOK" | python -m json.tool
```

### Проверить ключевое

| Сценарий | Как проверить | Ожидаемо |
|---|---|---|
| **Ссылка одноразовая** | Передать ссылку третьему аккаунту после того, как по ней вошли | Не сработает |
| **Продление суммирует дни** | Купить второй раз до окончания первого | `expires_at` сдвигается на +30 дней, не перезаписывается |
| **Отзыв по истечении** | См. ниже — ускорить срок | Пользователь удалён из канала, приходит уведомление |
| **Повторная покупка после истечения** | Купить снова | Работает — при отзыве делается `unban`, не вечный бан |
| **Сплит комиссии** | Сверка после покупки | Автору сумма минус комиссия, платформе комиссия |

Ускорить истечение для проверки:

```bash
docker compose exec postgres psql -U marketplace_user -d marketplace \
  -c "UPDATE subscriptions SET expires_at = now() - interval '1 hour' WHERE status='ACTIVE';"
```

Джоба ходит раз в час. Не ждать — дёрнуть вручную:

```bash
docker compose exec backend python -c "
import asyncio
from database import AsyncSessionLocal
from services import subscription_service as s
async def main():
    async with AsyncSessionLocal() as db:
        print('истекло:', await s.expire_due_subscriptions(db))
asyncio.run(main())"
```

### Журнал доступа

Главный инструмент при разборе «у меня нет доступа»:

```bash
curl -s "http://localhost:8080/api/admin/subscriptions/<subscription_id>/log" -H "Authorization: Bearer $ATOK" | python -m json.tool
```

Видно каждую выдачу ссылки, вход, выход, кик и **каждую ошибку Telegram с причиной**.

### Проверка сплита

```bash
curl -s "http://localhost:8080/api/admin/finance/accounts?currency=TON" -H "Authorization: Bearer $ATOK" | python -m json.tool
curl -s -X POST http://localhost:8080/api/admin/finance/reconcile -H "Authorization: Bearer $ATOK"
```

Сверка обязана сходиться после любых операций.

---

# 5. Полный прогон через туннель

Нужен для двух вещей: подписи транзакции кошельком и открытия Mini App кнопкой в боте.

На вашей машине уже стоят `ngrok` и `cloudflared`.

## Вариант A — cloudflared (без регистрации)

```bash
cloudflared tunnel --url http://localhost:8080
```

Выдаст адрес вида `https://something-random.trycloudflare.com`.

## Вариант B — ngrok

```bash
ngrok http 8080
```

## Что сделать после получения адреса

```bash
# 1. Прописать домен
sed -i 's|^SITE_URL=.*|SITE_URL=https://ваш-адрес|' .env
sed -i 's|^VITE_API_URL=.*|VITE_API_URL=https://ваш-адрес/api|' .env
sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=["https://ваш-адрес"]|' .env

# 2. Пересобрать фронт — манифест TON Connect генерируется на сборке
docker compose build frontend admin
docker compose up -d --force-recreate

# 3. Проверить манифест
curl -s https://ваш-адрес/tonconnect-manifest.json
# url внутри должен совпадать с вашим адресом
```

**В BotFather:** `/mybots` → ваш бот → Bot Settings → Menu Button → задать `https://ваш-адрес`.

Теперь `/start` в боте → кнопка → витрина открывается внутри Telegram, кошелёк подключается, оплата проходит.

> Адрес у бесплатного туннеля меняется при каждом перезапуске — придётся переделать шаги заново. Для долгого тестирования удобнее сервер.

---

# 6. Запуск на сервере

```bash
git clone <репозиторий> && cd marketplace
cp .env.example .env
```

В `.env` **обязательно**:

```ini
DEBUG=false
VITE_DEV_AUTH=false
COOKIE_SECURE=true
SITE_URL=https://ваш-домен
VITE_API_URL=https://ваш-домен/api
CORS_ORIGINS=["https://ваш-домен"]
```

```bash
# ВАЖНО: -f docker-compose.yml — без него подхватится локальный override
# с монтированием кода, автоперезагрузкой и открытым портом 8000
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.yml up -d
```

HTTPS: приложение слушает `8080`, сертификаты ставятся внешним nginx или Caddy перед ним.

## Перед выкаткой проверить

- [ ] `curl https://домен/api/auth/dev` → **404**
- [ ] `DEBUG=false`, `VITE_DEV_AUTH=false`, `COOKIE_SECURE=true`
- [ ] Все секреты из архива прошлого разработчика **ротированы** (токен бота, пароль БД, пароль админки, `SECRET_KEY`)
- [ ] `~/.ssh/authorized_keys` проверен у всех пользователей, включая `root`
- [ ] Настроены бэкапы БД
- [ ] `TON_NETWORK=mainnet` и боевой кошелёк — **только после полной проверки на testnet**

---

# 7. Траблшутинг

| Симптом | Причина и решение |
|---|---|
| Backend не стартует, в логах «Схема БД не соответствует коду» | Не накатаны миграции: `docker compose run --rm backend alembic upgrade head`. Так и задумано — лучше не стартовать, чем работать на чужой схеме |
| Витрина показывает «Откройте через Telegram» | `VITE_DEV_AUTH` не `true`, либо фронт не пересобран после правки `.env` |
| Изменения фронта не видны | Пересобрать: `docker compose build frontend && docker compose up -d --force-recreate frontend`. Файлы копируются в общий том при старте контейнера |
| Не входит в админку, куки не сохраняются | По HTTP нужен `COOKIE_SECURE=false` |
| `/api/payments/check/...` → 503 | Индексер недоступен или упёрлись в лимит. Получите `TON_API_KEY` |
| Кошелёк не открывается / «manifest error» | TON Connect не работает с `localhost`. Нужен туннель или домен |
| Бот не отвечает | Тот же токен используется где-то ещё. `docker compose logs bot` |
| Подписка куплена, ссылка не пришла | `docker compose logs backend \| grep "\[SUB\]"` и журнал доступа. Обычно бот не админ канала или лишился прав |
| Пользователя не удалило из канала | Журнал доступа покажет причину. Подписка закрывается в любом случае — это защита от «вечно активных» записей |

Полезное:

```bash
docker compose logs -f backend            # все логи бэкенда
docker compose logs -f bot                # бот
docker compose exec postgres psql -U marketplace_user -d marketplace   # консоль БД
docker compose down && docker compose up -d                            # перезапуск
docker compose down -v                    # ПОЛНЫЙ СБРОС, удалит и данные БД
```

---

# 8. Короткий чеклист приёмки

**Локально:**

- [ ] 66 автотестов проходят
- [ ] Пять контейнеров подняты и healthy
- [ ] Витрина и админка открываются
- [ ] `/api/auth/dev` при `DEBUG=false` даёт 404
- [ ] Перебор пароля админки отбивается 429
- [ ] Корзина из 3 товаров → **один** заказ и **один** счёт
- [ ] Настройки меняются в админке, невалидные значения отбиваются
- [ ] Сверка финансов: `ok: true`, суммы по валютам 0
- [ ] Двойное подтверждение вывода не списывает дважды
- [ ] Канал без прав бота не публикуется
- [ ] Подписка куплена, ссылка пришла, доступ выдан
- [ ] Продление суммирует дни
- [ ] По истечении пользователь удалён и может купить снова
- [ ] Сверка сходится после всех операций

**Через туннель или на сервере:**

- [ ] Mini App открывается кнопкой в боте
- [ ] Кошелёк подключается, транзакция подписывается
- [ ] Заказ оплачен, товар пришёл в бот
- [ ] Недоплата не выдаёт товар и шлёт алерт
- [ ] Неоплаченный заказ отменяется, товар возвращается в сток
