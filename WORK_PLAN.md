# План работ / промпт для Claude Code — Marketplace 2.0

> Версия 2. Составлен на основе: аудита кода (`ESTIMATE.md`), первой версии задания (`CLAUDE_CODE_TASK.md`) и полной переписки с заказчиком.
> Дата: 2026-09-13.

---

# ЧАСТЬ I. КАК РАБОТАТЬ

## Роль

Ты — исполнитель по доработке боевого Telegram Mini App маркетплейса, доставшегося от предыдущего разработчика. Проект **работает в проде с реальными пользователями, товарами и заказами**. Приоритет №1 — ничего не сломать в существующей логике товаров и заказов.

## Правила

1. **Перед каждым этапом** — короткий план: какие файлы затрагиваются, какие миграции создаются, что может сломаться. Дождись подтверждения, прежде чем начинать.
2. **Не начинай этапы 2+, пока не закрыты этапы 0 и 1.** Без чистых миграций любая новая таблица ломает БД.
3. **Каждый этап — законченный кусок**, который можно отдельно принять, задеплоить и откатить.
4. **Не изобретай данных.** Если чего-то нет в коде или в этом документе — спроси, не додумывай.
5. **Деньги — только целые числа.** Никакого `float` в финансовой логике. TON — в нанотонах (`BigInteger`, 1 TON = 1 000 000 000 нанотон), USD — `Numeric(10,2)`.
6. **Каждая денежная операция идемпотентна.** Повторный вызов не должен создавать второе начисление.
7. **Никогда не доверяй фронтенду в вопросах оплаты.** Факт оплаты подтверждается только проверкой в блокчейне на стороне бэкенда.
8. **Миграции только через Alembic**, каждая проверяется на копии боевой БД до применения. Автосгенерированные миграции читать глазами — в этом проекте autogenerate предлагает деструктивные изменения (см. этап 1).
9. **Логирование вместо `print()`.** В проекте ~60 `print()`. Заменять на `logging` в тех файлах, которых касаешься.
10. После каждого этапа — отчёт: что сделано, что протестировано, что осталось согласовать.

---

# ЧАСТЬ II. КОНТЕКСТ

## Стек

| Слой | Технологии |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2.0 (async), asyncpg, Alembic, Pydantic v2, APScheduler |
| БД | PostgreSQL 17 |
| Витрина | React 19, TypeScript, Vite 7, react-router 7, zustand, framer-motion, `@twa-dev/sdk` |
| Админка | React 19, TypeScript, Vite, TanStack Query, Tailwind 4 |
| Бот | aiogram 3 (long polling), отдельный контейнер |
| Оплата | CryptoBot / `aiocryptopay` — **подлежит замене** |
| Инфра | Docker Compose (postgres/backend/frontend/admin/bot/nginx) |

## Карта существующего кода

```
backend/
  main.py              CORS, /uploads, WebSocket /ws, роутеры,
                       lifespan -> create_all() + APScheduler   [create_all убрать, этап 1]
  config.py            pydantic-settings; DEBUG по умолчанию True  [ЧИНИТЬ, этап 0]
  database.py          async engine + get_db()
  models/              User, Product, Category, CartItem, Order+OrderItem, Payment(пустая),
                       Review, DigitalItem, ReferralTransaction, Withdrawal
                       + order_item.py — ДУБЛЬ OrderItem, удалить
  routes/              auth, products, categories, cart, orders, payments, reviews,
                       users, withdrawals, admin_auth, admin_stats, admin_orders
  services/            payment_service (CryptoBot), telegram_service (Bot API через httpx),
                       referral_service (жёсткие 3%), scheduler (APScheduler)
  utils/               auth (JWT + Telegram initData + bcrypt), admin_deps, websockets
  alembic/versions/    3 миграции, схема неполная            [ЧИНИТЬ, этап 1]

frontend/src/          App, api/client.ts, store/{auth,cart}, hooks/{useTelegram,useTheme,useWebSocket},
                       components/{Header,BottomNav,ProductCard,CartSummary},
                       pages/{Home,Cart,Checkout,ProductDetails,Profile}
                       /orders — заглушка «Coming Soon»

admin/src/pages/       Dashboard, ProcessingPage, Products, Categories, Orders,
                       Users(слабая), Reviews, Withdrawals, Login

bot/bot.py             90 строк, умеет только /start + проброс ref-кода
```

## Что критично знать о текущем коде

| Факт | Файл | Следствие |
|---|---|---|
| `complete_order()` — единственная точка выдачи товара, про платёжку не знает | `backend/routes/orders.py:248` | Переиспользуется как есть при замене оплаты. Все новые типы товара (подписка, P2P) добавляются веткой здесь |
| На **каждую позицию корзины создаётся отдельный заказ** со своим инвойсом | `backend/routes/orders.py:102` | С TON Connect = N подписей в кошельке. **Объединяем в один заказ** (согласовано) |
| Выпуск инвойса вшит в тело `create_order` | `backend/routes/orders.py:212` | Расщепить: создание заказа ≠ инициация оплаты |
| Таблица `payments` создана, но нигде не используется | `backend/models/payment.py` | Готовое место под журнал TON-платежей |
| Баланс = одно поле `Float` `users.referral_earnings` | `backend/models/user.py:31` | Не годится ни под сплит, ни под escrow. Нужен финслой (этап 2) |
| Рефералка = жёсткие 3% из `settings.REFERRAL_PERCENTAGE` | `backend/services/referral_service.py:31` | Проценты выносим в настройки (этап 6) |
| `users.is_blocked` есть в БД, нет в модели | миграция `...add_product_types.py:38` | Колонка уже есть — блокировки реализуются без новой миграции |
| У товара **одна картинка** — `image_url: String(500)` | `backend/models/product.py` | Для P2P (несколько фото) нужна отдельная таблица изображений |
| Отзыв привязан к `order_id`, текст ≤150 символов | `backend/schemas/review.py:12` | Расширяем на P2P: отзыв о продавце, а не только о товаре |
| APScheduler уже поднят, есть джоба очистки резервов | `backend/services/scheduler.py` | Новые джобы (подписки, escrow-дедлайны) добавляются туда |
| WebSocket `ConnectionManager` работает, broadcast используется | `backend/utils/websockets.py` | Готовая инфраструктура для внутреннего чата сделок (этап 5) |

---

# ЧАСТЬ III. ОГРАНИЧЕНИЯ TELEGRAM — ПРОЧИТАТЬ ДО ПРОЕКТИРОВАНИЯ

**Три пункта ТЗ заказчика технически невыполнимы в том виде, как записаны.** Это не придирка — если проектировать «как написано», этап 5 упрётся в стену на середине.

### Т1. Бот НЕ МОЖЕТ добавить пользователя в чат по `user_id`

В ТЗ: *«бот... добавляет туда обоих участников по их user_id»*.

Метода `addChatMember` в Bot API **не существует** (он есть только в клиентском MTProto API, не в ботовом). Единственный способ — бот создаёт **персональную инвайт-ссылку** (`createChatInviteLink`) и отправляет её каждому участнику, а они переходят сами.

**Как делаем:** `createChatInviteLink(chat_id, member_limit=1, expire_date=...)` отдельно для покупателя и продавца. Параметры `member_limit` и `creates_join_request` взаимоисключающие — использовать `member_limit=1`. Факт входа ловим апдейтом `chat_member`.

### Т2. Бот НЕ МОЖЕТ создать группу или супергруппу

В ТЗ: *«createGroup»*. Метода `createGroup` в Bot API **нет**. Боты не умеют создавать чаты вообще.

`createForumTopic` — существует, но создаёт **топик внутри уже существующей супергруппы-форума**, где бот является администратором с правом `can_manage_topics`, и у супергруппы включён режим форума.

### Т3. Форум-топик НЕ приватный

Самое важное. **В супергруппе-форуме все участники видят все топики.** Пер-топиковых прав доступа в Telegram нет. Если завести одну супергруппу и создавать в ней топик на каждую сделку — каждый покупатель увидит переписку по всем чужим сделкам: цены, договорённости, контакты, споры.

Для маркетплейса с денежными сделками это неприемлемо.

### Варианты решения этапа 5 (выбрать с заказчиком)

| Вариант | Приватность | Реализуемость | Комментарий |
|---|---|---|---|
| **A. Чат сделки внутри Mini App** (рекомендуется) | Полная | Высокая — WebSocket-инфраструктура уже есть | Свой UI чата, бот шлёт уведомления «новое сообщение по сделке». Вся переписка в нашей БД → железные доказательства в споре, модерация, автоматические стоп-слова. Полный контроль |
| **B. Одна супергруппа-форум + топик на сделку** | **Нет** | Высокая | Дёшево и быстро, но переписка всех сделок видна всем участникам. Годится только если заказчик осознанно согласен |
| **C. Пул заранее созданных групп** | Полная | Средняя | Группы создаёт человек руками заранее, бот раздаёт из пула и чистит после сделки. Не масштабируется, требует ручного пополнения |
| **D. Userbot (Telethon/Pyrogram на реальном аккаунте) создаёт группу на сделку** | Полная | Низкая | Технически работает, но это отдельный процесс с сессией живого аккаунта, риск бана аккаунта Telegram, серая зона правил. Не рекомендую для боевого продукта с деньгами |

| **E. Релей через бота** (ВЫБРАНО) | Полная | Высокая | Бот пересылает сообщения между личками сторон. Групп и топиков нет вообще |

### РЕШЕНИЕ ЗАКАЗЧИКА: вариант E — релей через бота

Так работает P2P в TG Wallet. Покупатель пишет боту в личку, бот пересылает
продавцу в его личку, и наоборот.

Сочетает сильные стороны A и B: приватность полная (каждая пара видит только
свой диалог), переписка целиком в нашей БД (доказательства в споре, модерация,
стоп-слова), при этом люди остаются в привычном интерфейсе Telegram.

Отпадает целый пласт работы: создание групп, инвайты, управление участниками,
проверка прав бота в чате сделки, чистка после закрытия.

**Пересылка только через `copyMessage`, не `forwardMessage`.** Копия приходит
без пометки «переслано от», то есть стороны НЕ видят username и профиль друг
друга. Это согласовано с заказчиком: анонимность через платформу защищает от
увода сделки мимо escrow.

**Маршрутизация — главная сложность.** У человека может быть несколько активных
сделок, и непонятно, в какую адресовать очередное сообщение. Решение:
  * основное — «активная сделка»: после покупки она становится текущей, обычные
    сообщения летят в неё, переключение инлайн-кнопкой;
  * дополнительно — reply на конкретное сообщение контрагента определяет сделку
    по нему и перекрывает активную.
Каждое пересланное сообщение подписывается шапкой «Сделка №N · Товар».

**Согласовано отдельно:**
  * стороны не видят контактов друг друга;
  * после завершения сделки чат закрывается на запись, история остаётся читаемой.

**Что предусмотреть:** пользователь заблокировал бота (ловим 403, сообщаем
контрагенту), оба должны были нажать /start, лимит Telegram ~1 сообщение в
секунду на чат (при росте — очередь), системные сообщения платформы падают в
тот же поток.

### Т4. Прочие ограничения, которые надо учесть

- **Апдейт `chat_member` по умолчанию не приходит.** Его нужно явно перечислить в `allowed_updates` при `getUpdates`/`setWebhook`. В aiogram 3 — зарегистрировать хендлер и передать `allowed_updates=dp.resolve_used_update_types()`.
- **Кик из канала** = `banChatMember(chat_id, user_id)` затем `unbanChatMember(chat_id, user_id, only_if_banned=True)` — иначе пользователь останется в вечном бане и не сможет купить подписку повторно.
- **Бот обязан быть админом** в каждом канале автора (право приглашать + банить) и в чате сделок (право управлять топиками). Технически проверять при подключении канала через `getChatMember(chat_id, bot_id)` и **не публиковать** канал, пока проверка не пройдена. Это же должно быть в условиях площадки.
- **Кастомные эмодзи требуют Premium** — к текущему проекту не относится (тема эмодзи-редактора закрыта), но если всплывёт: показывать уведомление.

---

# ЧАСТЬ IV. ЭТАПЫ РАБОТ

Порядок обязательный: 0 → 1 → 2 → далее.

---

## ЭТАП 0 — Критичные фиксы безопасности

**Цель:** закрыть дыры, через которые прямо сейчас можно зайти админом и получить товар без оплаты.
**Блокирующий. Делать первым, до всего остального.**

### 0.1. Закрыть dev-эндпоинт авторизации

- В `backend/config.py:27` `DEBUG: bool = True` по умолчанию. В `.env` переменная **не задана** → на проде dev-режим включён.
- Из-за этого открыт `POST /api/auth/dev` (`backend/routes/auth.py:71`), выдающий JWT с `is_admin: True` **любому без пароля**.
- Побочно: `echo=settings.DEBUG` в `backend/database.py` → весь SQL пишется в логи.

**Сделать:**
1. `DEBUG: bool = False` по умолчанию в `config.py`.
2. Явно прописать `DEBUG=false` в `.env` и в `.env.example`.
3. Эндпоинт `/api/auth/dev` регистрировать только при `settings.DEBUG is True` (не просто возвращать 403 — не регистрировать роут вообще).
4. Проверить: при `DEBUG=false` запрос к `/api/auth/dev` даёт 404.

### 0.2. Проверка подлинности вебхука оплаты

- `backend/routes/payments.py:31` — комментарий «Verify webhook (aiocryptopay handles this)» не соответствует коду. Тело читается как сырой JSON, подпись не проверяется.
- Любой может отправить `POST /api/webhook/crypto` с чужим `order_id` и получить товар бесплатно.

**Сделать:** реализовать проверку подписи вебхука CryptoBot (HMAC-SHA256 от тела запроса с ключом = SHA256 от API-токена, сверка с заголовком `crypto-pay-api-signature`). Неподписанный запрос → 401, заказ не трогаем.

> Живёт до этапа 3, потом весь этот роут удаляется вместе с CryptoBot. Но два-три дня до релиза TON Connect дыра существовать не должна.

### 0.3. Валидация Telegram initData — добавить TTL

`backend/utils/auth.py:26` — подпись проверяется, но `auth_date` игнорируется. Перехваченный initData работает бессрочно.

**Сделать:** отклонять initData старше 24 часов (значение в настройки).

### 0.4. Аудит остальных роутов

Пройти по всем роутерам, составить таблицу «эндпоинт → требуемая авторизация → фактическая». Проверить, что:
- все `/admin/*` закрыты `require_admin` или `get_current_admin_user`;
- пользовательские эндпоинты проверяют владельца ресурса (не только факт авторизации);
- `GET /api/orders/{order_id}` проверяет `order.user_id == user.id` — **проверено, работает**, использовать как образец.

Результат — список найденного, чинить по согласованию.

### 0.5. Удалить дубликат модели

`backend/models/order_item.py` объявляет второй `OrderItem` с тем же `__tablename__ = "order_items"`, что и `backend/models/order.py:75`. Сейчас файл не импортируется, но любой импорт `models.order_item` уронит приложение на старте с `Table 'order_items' is already defined`.

**Сделать:** удалить файл, убедиться, что нигде не импортируется.

### Критерии приёмки этапа 0

- [ ] `POST /api/auth/dev` на проде отдаёт 404
- [ ] Поддельный вебхук не переводит заказ в `paid`
- [ ] initData старше суток отклоняется
- [ ] `models/order_item.py` удалён, приложение стартует
- [ ] Таблица аудита роутов приложена к отчёту

### Вне кода — на стороне владельца проекта

Напомнить в отчёте (сам не делаю, доступа нет):
- **Ротировать все секреты**, они лежали в архиве в открытом виде: `TELEGRAM_BOT_TOKEN`, `CRYPTOBOT_API_TOKEN`, `DB_PASSWORD`, `ADMIN_PASSWORD`, `SECRET_KEY`.
- **Проверить `~/.ssh/authorized_keys` на сервере** — заказчик сообщил, что предыдущий разработчик оставил там свой ключ. Проверить у всех пользователей, включая `root`.
- Заодно: `docker ps` на предмет лишних контейнеров, `crontab -l`, открытые порты (`ss -tulpn`), systemd-юниты.
- Заказчик планировал разворачивать проект заново на чистом сервере — это правильное решение, поддержать.

---

## ЭТАП 1 — Приведение миграций в порядок

**Цель:** сделать так, чтобы `alembic revision --autogenerate` можно было запускать без риска снести данные.
**Блокирующий.** Без него этапы 3–5 (а там 12+ новых таблиц) сломают прод.

### Проблемы

1. **Три таблицы из десяти не имеют ни одной миграции:** `digital_items`, `payments`, `withdrawals`. Существуют только потому, что `backend/main.py:31-32` вызывает `Base.metadata.create_all()` при каждом старте.
2. `alembic upgrade head` на чистой БД даёт **неполную схему**.
3. **Расхождения модель ↔ миграция:**
   - `users.is_blocked` — есть в миграции, нет в модели → autogenerate сгенерирует `drop_column`;
   - `order_items.product_id` — в миграции `NOT NULL` + `CASCADE`, в модели `nullable=True` + `SET NULL` → autogenerate сгенерирует `alter_column` и пересоздание FK.

### Задачи

1. **Снять дамп схемы боевой БД** (`pg_dump --schema-only`) — это источник истины о фактическом состоянии.
2. **Вернуть `is_blocked` в модель `User`** (`Boolean, default=False, nullable=False`) — колонка в БД уже есть, миграция не нужна, и она понадобится для блокировок в этапах 5 и 7.
3. **Решить по `order_items.product_id`:** модель (`nullable=True` + `SET NULL`) правильнее — при удалении товара заказ должен сохраниться, снапшот товара в `product_snapshot` уже есть. Написать миграцию, приводящую БД к модели.
4. **Baseline-миграция** для `digital_items`, `payments`, `withdrawals`: создаёт таблицы, если их нет (проверка через `inspect(conn).has_table(...)`, а не слепой `create_table`). На проде это no-op, на чистой БД создаёт схему.
5. **Убрать `Base.metadata.create_all()`** из `backend/main.py`. Схема — только через Alembic.
6. **Проверка:**
   - на чистой БД `alembic upgrade head` → полная схема, приложение стартует, `seed.py` отрабатывает;
   - на копии боевой БД `alembic upgrade head` → нет изменений данных;
   - `alembic revision --autogenerate` вхолостую → пустая миграция (никаких `drop_column`/`alter_column`).
7. **Зафиксировать правило в README:** каждая новая миграция читается глазами перед применением.

### Критерии приёмки этапа 1

- [ ] `alembic upgrade head` на пустой БД поднимает полную рабочую схему
- [ ] На копии прод-БД миграции проходят без потери данных
- [ ] `--autogenerate` генерирует пустую миграцию
- [ ] `create_all()` удалён из `main.py`
- [ ] Приложены до/после дампы схемы

---

## ЭТАП 2 — Финансовый слой

**Цель:** единое ядро для денег, на которое лягут TON-оплата, комиссии, escrow, подписки и рефералка.
**Делать до этапов 3–6.** Иначе финансовая логика размажется по четырём местам и будет расходиться.

### Почему нужен

Сейчас все деньги в системе — это одно поле `users.referral_earnings` типа `Float`. Ни сплита, ни escrow, ни истории начислений, ни ответа на вопрос «из чего сложился баланс». Плюс `Float` для денег накапливает погрешность.

### Схема данных

```python
# backend/models/finance.py

class Account(Base):
    """Кошелёк-баланс внутри системы."""
    __tablename__ = "accounts"
    id: UUID (pk)
    owner_type: Enum('platform', 'user')       # platform — единственный, системный
    owner_id: UUID | None  FK users.id         # NULL для платформы
    currency: String(10) = 'TON'
    balance_nano: BigInteger = 0               # доступно к выводу
    hold_nano: BigInteger = 0                  # заморожено (escrow, заявка на вывод)
    created_at / updated_at
    UNIQUE (owner_type, owner_id, currency)


class LedgerEntry(Base):
    """Журнал операций. Единственный источник правды по деньгам."""
    __tablename__ = "ledger_entries"
    id: UUID (pk)
    account_id: UUID FK accounts.id
    amount_nano: BigInteger                    # со знаком: + приход, − расход
    hold_delta_nano: BigInteger = 0            # изменение заморозки
    entry_type: Enum(
        'payment_in',            # платёж покупателя зашёл на счёт платформы
        'commission',            # комиссия платформы
        'seller_accrual',        # начисление продавцу
        'author_accrual',        # начисление автору канала (подписки)
        'referral_accrual',      # реферальное начисление
        'escrow_hold',           # заморозка на время сделки
        'escrow_release',        # разморозка в пользу продавца
        'escrow_refund',         # возврат покупателю
        'withdrawal_reserve',    # резерв под заявку на вывод
        'withdrawal_complete',   # вывод выполнен
        'withdrawal_cancel',     # заявка отменена, резерв снят
        'manual_adjust'          # ручная корректировка админом
    )
    ref_type: Enum('order','deal','subscription','withdrawal','manual')
    ref_id: UUID | None
    idempotency_key: String(128) UNIQUE        # напр. f"{ref_type}:{ref_id}:{entry_type}:{account_id}"
    comment: Text | None
    created_by_admin_id: UUID | None
    created_at
    INDEX (account_id, created_at)
```

### Правила

1. **Баланс никогда не пишется напрямую.** Только через сервис `finance_service.post_entries(...)`, который атомарно в одной транзакции пишет записи в `ledger_entries` и обновляет `accounts`.
2. **Идемпотентность через `idempotency_key`.** Повторный вызов с тем же ключом → `IntegrityError` → операция считается уже выполненной, ошибки наружу нет.
3. **Сумма всех `amount_nano` по всем счетам всегда равна сумме входящих платежей минус сумма выплат.** Написать функцию сверки `finance_service.reconcile()` и джобу, которая раз в сутки проверяет и алертит админу в Telegram при расхождении.
4. **Только целые нанотоны.** Комиссия считается как `amount_nano * percent_bp // 10000` (percent_bp — базисные пункты, 2% = 200), остаток идёт продавцу. Никакого округления в пользу «потерянных» нанотон.

### Настройки в админке

```python
class AppSetting(Base):
    __tablename__ = "app_settings"
    key: String(100) (pk)
    value: JSONB
    description: String(500)
    updated_at
    updated_by_admin_id: UUID | None
```

Стартовый набор ключей:

| Ключ | Тип | Смысл | Дефолт |
|---|---|---|---|
| `commission_p2p_bp` | int | Комиссия с P2P-сделки, базисные пункты | 200 (2%) |
| `commission_subscription_bp` | int | Комиссия с подписки | 200 |
| `referral_l1_bp` | int | Реферальные 1-го уровня | 300 (3%) |
| `referral_l2_bp` | int | Реферальные 2-го уровня (0 = выкл) | 0 |
| `referral_applies_to` | list | На что начисляется: `["product","subscription","p2p"]` | все |
| `ton_rate_source` | str | Источник курса | согласовать |
| `ton_rate_ttl_sec` | int | Сколько живёт зафиксированный курс | 900 |
| `order_payment_ttl_min` | int | Сколько ждём оплату заказа | 30 |
| `p2p_max_pending_listings` | int | Лимит заявок на модерации от одного продавца | 5 |
| `p2p_reject_block_threshold` | int | Отказов подряд до ограничения продавца | 3 |
| `p2p_confirm_deadline_days` | int | Автоподтверждение получения через N дней | 7 |
| `payout_min_nano` | int | Минимальная сумма вывода | — |
| `terms_version` | str | Текущая версия условий площадки | `1.0` |

Сервис `settings_service` с кешем в памяти и инвалидацией при изменении через админку. Значения из `AppSetting` **перекрывают** одноимённые из `.env`.

### Миграция существующих балансов

`users.referral_earnings` (Float, USD) → создать `Account` для каждого пользователя с ненулевым балансом, записать `LedgerEntry` типа `manual_adjust` с комментарием «перенос баланса из старой схемы».

**Важно:** старый баланс в USD, новый — в TON. Нужно решение заказчика: пересчитать по текущему курсу на дату миграции, или вести старые балансы отдельной валютой `USD` в том же `Account` (поле `currency` для этого и заведено). **Рекомендую второе** — не спорим с пользователями о курсе задним числом; старые USD-балансы выводятся как раньше, новые начисления идут в TON.

### Критерии приёмки этапа 2

- [ ] Баланс любого счёта = сумме его записей в журнале (проверяется тестом)
- [ ] Повторный вызов начисления с тем же ключом не удваивает сумму
- [ ] Существующие `referral_earnings` перенесены без потерь, сверка сходится
- [ ] Настройки читаются из БД, меняются через админку, кеш инвалидируется
- [ ] Юнит-тесты на расчёт комиссии (в т.ч. на неделимые остатки)

---

## ЭТАП 3 — Замена CryptoBot → TON Connect

**Цель:** приём оплаты напрямую на кошелёк платформы, подтверждение факта оплаты в блокчейне.

### 3.1. Объединить корзину в один заказ

Сейчас `backend/routes/orders.py:102` создаёт **отдельный заказ на каждую позицию корзины**. С TON Connect это N подписей в кошельке за один checkout.

**Сделать:** один checkout = один `Order` со всеми `OrderItem` = одна транзакция = одна подпись. Логика резервирования цифровых товаров (`SELECT ... FOR UPDATE`, `backend/routes/orders.py:139`) сохраняется, но применяется ко всем позициям в рамках одного заказа.

**Осторожно:** `complete_order()` уже умеет работать с несколькими `OrderItem` — там цикл по items. Ломаться не должно, но прогнать регресс.

### 3.2. Схема платежа

Расширяем существующую пустую таблицу `payments`:

```python
class Payment(Base):
    __tablename__ = "payments"
    id / order_id / user_id                    # уже есть
    provider: String(50) = 'ton_connect'
    amount_nano: BigInteger                    # сколько ждём, в нанотонах
    usd_amount: Numeric(10,2)                  # исходная цена в USD
    rate_usd_per_ton: Numeric(18,9)            # курс на момент фиксации
    rate_locked_at: DateTime
    expires_at: DateTime                       # rate_locked_at + ton_rate_ttl_sec
    destination_address: String(68)            # кошелёк платформы
    payment_comment: String(64) UNIQUE         # уникальный memo для сопоставления
    status: Enum('pending','seen','confirmed','underpaid','overpaid','expired','failed')
    tx_hash: String(64) UNIQUE | None
    tx_lt: BigInteger | None                   # logical time
    from_address: String(68) | None
    received_nano: BigInteger | None           # сколько реально пришло
    confirmed_at: DateTime | None
    created_at
    INDEX (status, expires_at), INDEX (payment_comment)
```

`orders.cryptobot_invoice_id` — **не удалять**, задепрекейтить (историю заказов терять нельзя).

### 3.3. Сервис `backend/services/ton_service.py`

```
get_rate() -> Decimal                    курс USD/TON, кеш на ton_rate_ttl_sec
create_payment(order) -> Payment         фиксирует курс, считает amount_nano,
                                         генерирует уникальный payment_comment
build_transaction(payment) -> dict       payload для TON Connect sendTransaction:
                                         { validUntil, messages: [{ address, amount, payload }] }
                                         payload = base64 BOC с текстовым комментарием
verify_payment(payment) -> PaymentResult проверка on-chain через индексер
```

**Проверка платежа (ключевое, тут нельзя срезать углы):**

1. Запросить у индексера транзакции на `destination_address` за окно `[rate_locked_at - 5min, expires_at + 30min]`.
2. Найти входящую транзакцию с комментарием == `payment_comment`.
3. Сверить сумму:
   - `received >= amount_nano` → `confirmed` (переплата — записать `overpaid`, но заказ выдать);
   - `received < amount_nano` → `underpaid`, заказ **не** выдавать, уведомить админа и пользователя.
4. Проверить, что `tx_hash` ещё не использован (UNIQUE + проверка перед записью) — защита от повторного зачёта.
5. Только после `confirmed` вызвать `complete_order(order, db)`.

**Никогда не подтверждать оплату по сообщению от фронта.** Фронт может прислать `boc`/хэш как подсказку для ускорения проверки, но решение принимается только по данным индексера.

### 3.4. Поллер подтверждений

Джоба в `backend/services/scheduler.py`, интервал ~15 сек:
- берёт `Payment` в статусе `pending`/`seen` с `expires_at > now()`;
- вызывает `verify_payment`;
- при `confirmed` → `complete_order` (в транзакции, идемпотентно);
- при истечении `expires_at` → `expired`, заказ в `cancelled`, резервы освобождаются.

Плюс ручная кнопка «я оплатил» на фронте → внеочередная проверка конкретного платежа (с рейт-лимитом).

### 3.5. Согласовать окна времени

Сейчас несогласованно: резерв цифровых товаров — **3 минуты** (`backend/routes/orders.py:124`), автоотмена pending-заказов — **120 минут** (`backend/services/scheduler.py:31`).

Свести к одному значению `order_payment_ttl_min` (по умолчанию 30 мин): резерв товара держится ровно столько же, сколько живёт платёж.

### 3.6. Edge-кейсы (реализовать явно, не «потом»)

| Ситуация | Поведение |
|---|---|
| Недоплата | Заказ не выдаётся, статус `underpaid`, уведомление админу и пользователю, ручное решение |
| Переплата | Заказ выдаётся, разница фиксируется в журнале, уведомление админу |
| Платёж после автоотмены заказа | **Согласовать с заказчиком.** Рекомендую: зачислить на внутренний баланс пользователя + уведомить, чем возвращать вручную |
| Повторная отправка того же платежа | UNIQUE по `tx_hash`, второй зачёт невозможен |
| Курс уплыл между показом цены и оплатой | Курс зафиксирован в `Payment` на `ton_rate_ttl_sec`, после истечения — новый заказ |
| Индексер недоступен | Ретраи с backoff, платёж остаётся `pending`, алерт админу при недоступности > N минут |

### 3.7. Фронтенд

- `@tonconnect/ui-react`, манифест `tonconnect-manifest.json` раздаётся по HTTPS с корня (правка `nginx/nginx.conf`).
- Кнопка подключения кошелька, `sendTransaction` с `validUntil`.
- Внутри Telegram Mini App указать `twaReturnUrl`, чтобы после подписи возвращало в приложение.
- Экран ожидания подтверждения (поллинг статуса — существующая логика в `Checkout.tsx:38-70` переиспользуется почти как есть).
- Обработка: пользователь отклонил подпись, закрыл кошелёк, кошелёк не установлен.

### 3.8. Цены в TON в админке

`products.price_ton` в форме админки не редактируется (`admin/src/pages/Products.tsx:136-153` отправляет только `price_usdt`). Решить с заказчиком:
- **(рекомендую)** цена задаётся в USD, в TON пересчитывается по курсу на момент заказа — тогда `price_ton` не нужен вовсе;
- либо цена фиксируется в TON — тогда добавить поле в форму и убрать конвертацию.

### 3.9. Удалить CryptoBot

После приёмки: `backend/services/payment_service.py`, роут вебхука, `aiocryptopay` из `requirements.txt`, `CRYPTOBOT_*` из конфига и `.env`. Отозвать токен CryptoBot в личном кабинете.

### Затрагиваемые файлы

`backend/services/ton_service.py` (новый) · `backend/services/payment_service.py` (удалить) · `backend/routes/orders.py` · `backend/routes/payments.py` · `backend/models/payment.py` · `backend/models/order.py` · `backend/schemas/payment.py`, `schemas/order.py` · `backend/services/scheduler.py` · `backend/config.py` · `backend/requirements.txt` · миграция · `frontend/src/pages/Checkout/Checkout.tsx` · `frontend/src/api/client.ts` · `frontend/src/types/index.ts` · `frontend/package.json` · `frontend/public/tonconnect-manifest.json` (новый) · `nginx/nginx.conf`

### Критерии приёмки этапа 3

- [ ] Корзина из 3 товаров = один заказ = одна подпись в кошельке
- [ ] Оплата на testnet проходит, товар выдаётся, ledger записан
- [ ] Попытка подтвердить оплату запросом с фронта без реальной транзакции — не проходит
- [ ] Недоплата не выдаёт товар
- [ ] Повторная проверка того же платежа не выдаёт товар дважды
- [ ] Истёкший платёж отменяет заказ и освобождает резерв
- [ ] CryptoBot полностью удалён, старые заказы в истории отображаются

---

## ЭТАП 4 — Подписки на закрытые каналы

**Цель:** автор подключает свой закрытый канал, продаёт доступ по подписке; выдача и отзыв доступа автоматические; платформа удерживает комиссию.

### 4.1. Схема данных

```python
class Channel(Base):
    __tablename__ = "channels"
    id: UUID
    owner_user_id: UUID FK users.id
    telegram_chat_id: BigInteger UNIQUE
    title: String(255)
    username: String(255) | None            # публичный @, если есть
    description: Text | None
    avatar_url: String(500) | None
    payout_wallet: String(68)               # TON-кошелёк автора
    bot_is_admin: Boolean = False           # результат проверки
    bot_checked_at: DateTime | None
    status: Enum('draft','pending','active','suspended','rejected')
    moderation_comment: Text | None
    created_at


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    id: UUID
    channel_id: UUID FK channels.id
    title_ru / title_en: String(255)
    duration_days: Integer                  # 30 / 90 / 180 / 365
    price_usd: Numeric(10,2)
    is_active: Boolean = True
    sort_order: Integer = 0
    created_at


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: UUID
    user_id: UUID FK users.id
    plan_id: UUID FK subscription_plans.id
    channel_id: UUID FK channels.id
    order_id: UUID FK orders.id | None
    status: Enum('pending','active','expiring','expired','revoked')
    started_at: DateTime | None
    expires_at: DateTime | None
    invite_link: String(255) | None
    invite_link_expires_at: DateTime | None
    joined_at: DateTime | None              # подтверждён вход по chat_member
    revoked_at: DateTime | None
    reminder_sent_at: DateTime | None
    created_at
    INDEX (status, expires_at)
    INDEX (user_id, channel_id)


class SubscriptionAccessLog(Base):
    __tablename__ = "subscription_access_log"
    id: UUID
    subscription_id: UUID FK
    action: Enum('invite_created','joined','left','kicked','revoke_failed','restored')
    detail: JSONB                            # ответ Telegram API, ошибки
    created_at
```

### 4.2. Подключение канала автором

1. Автор в Mini App заводит канал: указывает `@username` или пересылает сообщение из канала (получаем `chat_id`).
2. Показываем инструкцию: добавить бота админом с правами «приглашать» и «блокировать».
3. Кнопка «Проверить» → `getChatMember(chat_id, bot_id)` → проверяем `status == 'administrator'` и наличие `can_invite_users`, `can_restrict_members`. Результат в `bot_is_admin`.
4. Автор указывает TON-кошелёк для выплат (валидация формата адреса).
5. Автор принимает условия площадки (`TermsAcceptance`, роль `seller`).
6. Канал уходит на модерацию (`pending`) → админ одобряет → `active`.

**Без `bot_is_admin = True` канал не может быть переведён в `active`.**

### 4.3. Покупка и выдача доступа

Подписка — новый тип товара. В `complete_order()` (`backend/routes/orders.py:248`) добавляется ветка `product_snapshot["type"] == "subscription"`:

1. Создать/продлить `Subscription`:
   - новая → `started_at = now()`, `expires_at = now() + duration_days`;
   - активная существует → `expires_at += duration_days` (продление, не перезапись).
2. Начислить деньги через `finance_service`:
   - комиссия платформы = `amount_nano * commission_subscription_bp // 10000` → счёт платформы;
   - остаток → счёт автора канала;
   - реферальные, если применимо → счёт реферера.
3. Создать инвайт: `createChatInviteLink(chat_id, member_limit=1, expire_date=now+24h)`, сохранить в `Subscription.invite_link`.
4. Отправить пользователю ссылку через бота. Записать в `SubscriptionAccessLog`.
5. Ловить апдейт `chat_member` → при входе проставить `joined_at`.

**Важно:** ссылка одноразовая и с TTL. Если пользователь не успел — кнопка «получить ссылку заново» в профиле, пока подписка активна.

### 4.4. Отзыв доступа

Джоба в `scheduler.py`, раз в час:
- `Subscription` со `status='active'` и `expires_at < now()`:
  1. `banChatMember(chat_id, user_id)`;
  2. `unbanChatMember(chat_id, user_id, only_if_banned=True)` — чтобы не остался в вечном бане;
  3. статус → `expired`, запись в лог;
  4. уведомление пользователю с кнопкой «продлить».
- Ошибки (бот разжалован, канал удалён, пользователь уже вышел) — логировать как `revoke_failed`, уведомлять админа, не падать.

Вторая джоба, раз в сутки: напоминания за 3 дня и за 1 день до окончания.

### 4.5. Автопродление

**Ограничение, которое надо объяснить заказчику:** настоящего автосписания в TON Connect не бывает — каждая транзакция требует подписи пользователя в кошельке. Рекуррентных платежей нет.

Реализуем: напоминание + кнопка «Продлить» (создаёт новый заказ). Флаг `auto_renew` в UI не заводить, чтобы не вводить в заблуждение.

### 4.6. Выплаты авторам

Согласовано: **вручную**. Автор подаёт заявку на вывод → админ подтверждает в админке → переводит с кошелька платформы → отмечает выполненной. Механика уже есть в `backend/routes/withdrawals.py` и `admin/src/pages/Withdrawals.tsx` — расширить на счета из `accounts` вместо `users.referral_earnings`.

> Почему не автоматические выплаты: автоперевод требует хранить приватный ключ горячего кошелька на сервере. Учитывая, что у заказчика недавно был инцидент с чужим SSH-ключом на сервере, ручное подтверждение — осознанно правильный выбор. Автовыплаты можно вернуть позже, отдельным решением.

### 4.7. Витрина и админка

- Каталог каналов/подписок, карточка канала, тарифы.
- «Мои подписки» в профиле: статус, дата окончания, продлить, получить ссылку.
- Кабинет автора: свои каналы, тарифы, статистика подписчиков, баланс, заявка на вывод.
- Админка: модерация каналов, список подписок, ручная выдача/отзыв, настройки комиссии.

### Критерии приёмки этапа 4

- [ ] Канал без бота-админа нельзя опубликовать
- [ ] После оплаты приходит одноразовая инвайт-ссылка, вход фиксируется
- [ ] По истечении подписки пользователь удаляется из канала и может купить снова
- [ ] Продление активной подписки суммирует срок, а не обнуляет
- [ ] Комиссия и начисление автору сходятся в журнале до нанотона
- [ ] Разжалование бота в канале не роняет джобу, админ получает алерт

---

## ЭТАП 5 — P2P: пользователи продают свои товары

**Самый крупный и рискованный этап.** До начала — закрыть вопрос из части III (Т1–Т3): каким образом организуется чат сделки.

### 5.1. Профиль продавца

```python
class SellerProfile(Base):
    __tablename__ = "seller_profiles"
    id: UUID
    user_id: UUID FK users.id UNIQUE
    display_name: String(100)
    payout_wallet: String(68)
    status: Enum('active','restricted','banned')
    restricted_until: DateTime | None
    rating_avg: Numeric(3,2) | None
    rating_count: Integer = 0
    deals_completed: Integer = 0
    listings_rejected_streak: Integer = 0     # отказов подряд
    terms_version: String(20)
    terms_accepted_at: DateTime
    created_at
```

**Антифрод (пороги из `AppSetting`):**
- больше `p2p_max_pending_listings` заявок на модерации → новые не принимаются;
- `p2p_reject_block_threshold` отказов подряд → `restricted` на срок, уведомление;
- при нарушении условий → `banned` + `users.is_blocked = True` (колонка уже есть в БД).

### 5.2. Заявка на размещение и модерация

```python
class ProductListing(Base):
    __tablename__ = "product_listings"
    id: UUID
    seller_user_id: UUID FK users.id
    product_id: UUID FK products.id | None    # заполняется после одобрения
    category_id: UUID FK categories.id
    name_ru / name_en: String(500)
    description_ru / description_en: Text
    price_usd: Numeric(10,2)
    status: Enum('draft','pending','approved','rejected','withdrawn','archived')
    moderator_id: UUID | None
    moderation_comment: Text | None
    moderated_at: DateTime | None
    created_at


class ListingImage(Base):
    """У существующего Product одна картинка (image_url: String).
       Для P2P нужно несколько — отдельная таблица."""
    __tablename__ = "listing_images"
    id: UUID
    listing_id: UUID FK product_listings.id
    url: String(500)
    sort_order: Integer = 0
```

Расширение существующей модели `Product` (аддитивно, ничего не ломает):
```python
owner_user_id: UUID | None FK users.id     # NULL = товар платформы
is_p2p: Boolean = False
listing_id: UUID | None FK product_listings.id
```

**Флоу:** черновик → заявка (`pending`) → модератор одобряет/отклоняет → при одобрении создаётся `Product` с `is_p2p=True`, `owner_user_id` = продавец.

**Пометка на витрине обязательна:** бейдж «Товар пользователя» на карточке и на странице товара, визуально отличимый от товаров платформы. Плюс блок «продавец: имя, рейтинг, сделок».

**Валидация загрузок:** проверять реальный тип файла (не только расширение), лимит размера (`MAX_UPLOAD_SIZE` уже есть в конфиге), количество фото, пережимать через Pillow (уже в зависимостях). Не доверять `content-type` от клиента.

### 5.3. Сделка (escrow)

```python
class Deal(Base):
    __tablename__ = "deals"
    id: UUID
    order_id: UUID FK orders.id UNIQUE
    buyer_id: UUID FK users.id
    seller_id: UUID FK users.id
    product_id: UUID FK products.id
    amount_nano: BigInteger
    commission_nano: BigInteger
    seller_amount_nano: BigInteger
    status: Enum('created','paid_escrow','chat_opened','delivered_claimed',
                 'confirmed','released','disputed','refunded','cancelled')
    chat_kind: Enum('inapp','forum_topic')
    chat_id: BigInteger | None                # для forum_topic
    topic_id: Integer | None
    buyer_invite_link / seller_invite_link: String(255) | None
    confirm_deadline_at: DateTime             # автоподтверждение
    delivered_claimed_at / confirmed_at / released_at: DateTime | None
    dispute_opened_at: DateTime | None
    dispute_reason: Text | None
    resolved_by_admin_id: UUID | None
    resolution_comment: Text | None
    created_at
    INDEX (status, confirm_deadline_at)


class DealMessage(Base):
    """Для варианта A (чат внутри Mini App)."""
    __tablename__ = "deal_messages"
    id: UUID
    deal_id: UUID FK deals.id
    sender_id: UUID | None                    # NULL = системное сообщение
    text: Text
    attachments: JSONB | None
    is_system: Boolean = False
    read_by_buyer_at / read_by_seller_at: DateTime | None
    created_at
    INDEX (deal_id, created_at)
```

### 5.4. Конечный автомат сделки

```
                    оплата подтверждена on-chain
   [created] ─────────────────────────────────────> [paid_escrow]
                                                          │ деньги на счёте платформы,
                                                          │ hold_nano += amount
                                                          ▼
                                                   [chat_opened]
                                                          │ создан чат, обе стороны уведомлены
                                     ┌────────────────────┼────────────────────┐
                продавец «отправил»  │                    │ покупатель открыл  │
                                     ▼                    │ спор               ▼
                          [delivered_claimed]             │              [disputed]
                                     │                    │                    │
              покупатель подтвердил  │  дедлайн истёк     │        решение админа
                    или автоподтв.   ▼                    │           ┌────────┴────────┐
                              [confirmed]                 │           ▼                 ▼
                                     │                    │      [released]        [refunded]
                       выплата ─────>▼                    │   продавцу         покупателю
                              [released]                  │
                                                          │
              отмена до оплаты ──> [cancelled]
```

**Правила переходов:**
- В `paid_escrow` деньги лежат на счёте платформы с `hold_nano`, продавцу **не начислены**.
- `confirmed` → `released`: снимается hold, начисляется продавцу (за вычетом комиссии), комиссия — платформе. Одной транзакцией через `finance_service`.
- `disputed` можно открыть **только до** `confirmed`. После подтверждения — нельзя (это в условиях площадки).
- Автоподтверждение через `p2p_confirm_deadline_days` (по умолчанию 7 дней) с момента `delivered_claimed`. За сутки до — напоминание покупателю.
- `refunded`: возврат покупателю **вручную** админом (согласовано с заказчиком), в журнале — `escrow_refund`.
- Каждый переход пишется в журнал (кто, когда, почему) — нужно для разбора споров.
- Идемпотентность: одна оплата = одна сделка = один чат. Повторный вызов не создаёт второй топик/чат.

### 5.5. Чат сделки

Реализация зависит от выбора в части III. При **варианте A (рекомендуемом)**:

- Экран чата в Mini App, доступен только участникам сделки и админам.
- Сообщения через существующий WebSocket (`backend/utils/websockets.py` — `ConnectionManager` с адресацией по `user_id` уже готов).
- Бот шлёт push-уведомление «новое сообщение по сделке #N» с кнопкой открытия Mini App.
- Системные сообщения от платформы в ленту: «оплата получена», «продавец отметил отправку», «спор открыт», «сделка завершена».
- Админ видит переписку в админке при разборе спора.
- Чат открывается **только после оплаты** и закрывается на запись после `released`/`refunded` (остаётся читаемым).

При **варианте B (форум-топик)** — `createForumTopic` в заранее созданной супергруппе, персональные инвайты обоим, обработка `chat_member`. **Обязательно** предупредить заказчика письменно, что переписка не приватна между сделками.

### 5.6. Отзывы

Существующая модель `Review` привязана к `order_id` и товару, текст ≤150 символов (`backend/schemas/review.py:12`), есть публикация в Telegram-канал и фейковые отзывы от админа.

**Расширить:**
- отзыв о **продавце** после `released` (поле `seller_id` в `Review`);
- пересчёт `SellerProfile.rating_avg` / `rating_count`;
- отзыв можно оставить только по завершённой сделке (проверка по `Deal.status == 'released'`);
- увеличить лимит текста для P2P-отзывов (150 символов мало для описания сделки) — согласовать.

### 5.7. Условия площадки

```python
class TermsAcceptance(Base):
    __tablename__ = "terms_acceptances"
    id: UUID
    user_id: UUID FK users.id
    telegram_id: BigInteger                   # дублируем на случай удаления юзера
    terms_version: String(20)
    role: Enum('buyer','seller','author')
    context: Enum('purchase','listing','channel','subscription')
    ref_type: String(30) | None
    ref_id: UUID | None
    accepted_at: DateTime
    INDEX (user_id, terms_version)
```

- Отдельная страница с текстом условий (версионируется через `terms_version`).
- **Чекбокс перед покупкой** — покупатель. Без галочки кнопка оплаты неактивна.
- **Чекбокс при размещении товара** — продавец. Без галочки заявка не отправляется.
- **Чекбокс при подключении канала** — автор.
- Каждое согласие фиксируется в БД с версией и временем. При смене версии условий — запрашивать заново.
- В тексте условий обязательно: бот должен быть админом канала автора; правила споров и возвратов; сроки подтверждения; основания для блокировки; порядок выплат.

> Текст условий пишет заказчик. Я реализую хранение, версионирование, отображение и фиксацию согласий.

### Критерии приёмки этапа 5

- [ ] Заявка проходит модерацию, товар публикуется с пометкой «товар пользователя»
- [ ] Продавец с превышенным лимитом заявок не может подать новую
- [ ] N отказов подряд ограничивают продавца автоматически
- [ ] Оплата P2P-товара замораживает деньги, продавцу они не начислены
- [ ] Чат создаётся один раз, доступен только участникам
- [ ] Подтверждение получения переводит деньги продавцу за вычетом комиссии, суммы сходятся
- [ ] Автоподтверждение срабатывает по дедлайну
- [ ] Спор блокирует автоподтверждение, админ может вернуть деньги
- [ ] Отзыв можно оставить только после завершённой сделки, рейтинг продавца пересчитывается
- [ ] Без галочки согласия покупка и размещение недоступны, согласие записано в БД

---

## ЭТАП 6 — Настраиваемая реферальная программа

Сейчас: жёсткие 3% из `settings.REFERRAL_PERCENTAGE`, начисление в `backend/services/referral_service.py:31`, баланс — `Float`.

**Сделать:**
1. Проценты — из `AppSetting` (`referral_l1_bp`, `referral_l2_bp`), редактируются в админке без передеплоя.
2. Начисления — через `finance_service` в `LedgerEntry` (тип `referral_accrual`), а не в `users.referral_earnings`.
3. Второй уровень рефералов (реферер реферера) — опционально, включается ненулевым `referral_l2_bp`.
4. Настройка, на что начисляется: товары платформы / подписки / P2P (`referral_applies_to`).
5. Расширить `ReferralTransaction`: `level`, `percent_bp_applied`, `source`, сумма в нанотонах.
6. **Существующие начисления не пересчитывать** — старые транзакции остаются как есть, новые правила применяются с момента изменения настройки.
7. В админке — история начислений с фильтрами, топ рефереров.

### Критерии приёмки этапа 6

- [ ] Изменение процента в админке применяется к следующей покупке без рестарта
- [ ] Начисления идут в журнал, баланс сходится
- [ ] Старые начисления не затронуты
- [ ] При выключенном `referral_applies_to` для типа — начисления нет

---

## ЭТАП 7 — Админ-панель

Заказчик оставил выбор («на сайте или в Telegram — как удобнее»).

**Решение: оставляем веб-админку**, она уже написана и работает (Products и Categories — в хорошем состоянии). Переписывать в бота — выбросить готовое. **Но добавляем в Telegram то, что реально нужно быстро:** уведомления с кнопками для модерации.

### 7.1. Доработка существующих разделов

| Раздел | Что делать |
|---|---|
| `Users` (76 строк, самая слабая) | Пагинация, поиск по `telegram_id`/username/имени, колонка баланса, карточка пользователя (заказы, рефералы, сделки, выводы), кнопка блокировки (`is_blocked` уже в БД) |
| `Orders` (208 строк) | Пагинация, фильтры по статусу и датам, поиск, карточка заказа с составом и данными платежа, ручная смена статуса |
| `Dashboard` (119 строк) | Графики выручки и заказов по дням, топ товаров, конверсия pending→paid, счётчики «ждут модерации» и «открытые споры» |
| `Withdrawals` | Расширить на счета из `accounts`; отдельно выводы рефералов / авторов / продавцов |
| Backend | Пагинация в `GET /api/admin/orders` и `GET /api/users/admin/all`; устранить N+1 в `backend/routes/admin_orders.py:151-207` (на каждый заказ отдельный запрос за позициями и за пользователем) |

### 7.2. Новые разделы

- **Настройки** — редактирование `AppSetting`: комиссии, реф.проценты, пороги антифрода, TTL, курс, версия условий.
- **Модерация P2P** — очередь заявок, просмотр фото, одобрить/отклонить с комментарием.
- **Сделки** — список, фильтр по статусу, карточка со статусом, перепиской и кнопками разрешения спора.
- **Каналы и подписки** — модерация каналов, тарифы, список подписчиков, ручная выдача/отзыв.
- **Финансы** — журнал операций с фильтрами, сверка балансов, выгрузка.
- **Условия площадки** — редактирование текста и версии.

### 7.3. Telegram-уведомления с действиями

Существующий `telegram_service` уже шлёт админу уведомления (новый заказ услуги, заявка на вывод, товар кончился). Добавить inline-кнопки:
- новая заявка на P2P-товар → «Одобрить» / «Отклонить»;
- открыт спор → «Открыть в админке»;
- заявка на вывод → «Открыть в админке».

Обработчики callback-кнопок — в боте, с проверкой, что нажимает админ.

### 7.4. Общее

- Единый компонент таблицы (сейчас разметка продублирована на 6 страницах).
- Единое состояние загрузки (сейчас где-то скелетон, где-то текст `Loading...`).
- Тосты вместо `alert()`.
- Роли администраторов — согласовать, нужны ли (сейчас один общий логин из `.env`).

### Критерии приёмки этапа 7

- [ ] Users: поиск, пагинация, карточка, блокировка работают
- [ ] Модерация P2P возможна и из админки, и кнопкой в Telegram
- [ ] Списки не грузят всю таблицу разом, N+1 устранён
- [ ] Все настройки из `AppSetting` меняются из UI и применяются без рестарта

---

## ЭТАП 8 — Дизайн витрины

База приличная: CSS-переменные, светлая/тёмная тема, framer-motion, ~2 560 строк CSS.

**Два варианта (выбирает заказчик):**

**A. Освежение** — полный набор токенов (отступы, радиусы, типографика, z-index — сейчас есть только цвета и тени), привязка к теме Telegram (`themeParams` сейчас практически игнорируется), скелетоны и пустые состояния (класс `.shimmer` есть, но используется только на экране авторизации), переработка `ProductCard` и сетки Home, чистка 20 инлайновых `style={{}}` и мусорных файлов (`ProductDetails_backup.tsx`, `*.css.part`).

**B. Полный редизайн** — всё из A + `ProductDetails`, `Cart`, `Checkout`, `Profile` (835 строк CSS, просится разбивка на компоненты), новая иконография, микроанимации.

**Плюс в обоих вариантах** — новые экраны из этапов 4–5 (подписки, кабинет продавца, чат сделки, условия площадки) должны быть в единой стилистике.

**Не трогать:** бизнес-логику, товары, структуру данных. Только визуальный слой.

Отдельный вопрос: 71 инлайновый тернарник `language === 'ru' ? ... : ...`. `i18next` в зависимостях есть, но не используется. Вынос в словари — +1 день, делается заодно при переписывании разметки.

Роут `/orders` — сейчас заглушка «Coming Soon» (`frontend/src/App.tsx:18`), при этом в нижней навигации на него можно попасть. Доделать или убрать.

---

## ЭТАП 9 — Приёмка, тесты, передача

1. **Тесты на денежную логику** (минимально необходимое, без фанатизма):
   - расчёт комиссии и сплита, включая неделимые остатки;
   - идемпотентность начислений;
   - переходы конечного автомата сделки;
   - верификация TON-платежа (замоканный индексер): недоплата, переплата, дубль, истечение;
   - истечение и отзыв подписки.
2. **Сверка балансов** — джоба + ручной прогон на боевых данных.
3. **Нагрузочная проверка** списков после устранения N+1.
4. **Документация:**
   - `README.md` — что за проект, как поднять локально, как задеплоить (сейчас README отсутствует);
   - `.env.example` со всеми переменными и комментариями, разделение test/prod;
   - описание схемы БД и конечного автомата сделки;
   - инструкция для админа: как модерировать, как разрешать споры, как делать выплаты.
5. **Бэкапы БД** — настроить регулярный дамп, проверить восстановление.
6. **Финальный прогон** всех сценариев на staging перед выкаткой.

---

# ЧАСТЬ V. СКВОЗНЫЕ ТРЕБОВАНИЯ

1. **Ничего не ломать:** после каждого этапа существующие товары, заказы и пользователи работают.
2. **Все схемы — через Alembic**, каждая миграция проверена на копии прода, читается глазами.
3. **Деньги — целые нанотоны**, никакого `float`.
4. **Идемпотентность** всех денежных и выдающих операций.
5. **Факт оплаты — только on-chain**, не по слову клиента.
6. **Логирование вместо `print()`** в файлах, которых касаешься; в денежной логике — обязательный аудит-лог (кто, что, когда, сколько).
7. **Rate limiting** на: создание заказов, заявки на размещение, проверку статуса платежа, сообщения в чате сделки.
8. **Обработка ошибок Telegram API:** бот разжалован, канал удалён, пользователь заблокировал бота, flood wait — не должны ронять джобы.
9. **Секреты — только в `.env`**, никогда в коде и в репозитории.
10. **Каждый этап приёмосдаточен отдельно.**

---

# ЧАСТЬ VI. ВОПРОСЫ К ЗАКАЗЧИКУ

**Блокирующие (без ответа этап не начать):**

1. **Чат сделки** — вариант A (внутри Mini App, приватно, рекомендую) или B (форум-топики, но переписка всех сделок видна всем участникам)? См. часть III.
2. **Выплаты продавцам и авторам** — подтвердить, что вручную (как вы писали). Автоматические потребуют хранить приватный ключ горячего кошелька на сервере.
3. **Старые USD-балансы** при переходе на TON: пересчитать по курсу на дату миграции или вести отдельной валютой (рекомендую второе)?
4. **Источник курса USD→TON** и на сколько «замораживаем» курс для заказа (по умолчанию 15 минут)?
5. **Цены товаров** задаются в USD с пересчётом в TON (рекомендую) или фиксируются в TON?
6. **Текст условий площадки** — нужен от вас. Я делаю страницу, версионирование и фиксацию согласий.

**Важные (нужны до соответствующего этапа):**

7. Платёж, пришедший после автоотмены заказа: зачислить на внутренний баланс (рекомендую) или возвращать вручную?
8. Комиссия: одна общая или разная для подписок и P2P? Стартовые значения?
9. Реферальные: сколько уровней, на что начисляются (товары платформы / подписки / P2P), проценты?
10. Пороги антифрода P2P: сколько заявок одновременно, сколько отказов подряд до ограничения, на какой срок ограничение?
11. Срок автоподтверждения получения товара (по умолчанию 7 дней)?
12. Кто модерирует P2P-заявки и разбирает споры — вы лично или будут отдельные модераторы (нужны ли роли в админке)?
13. Дизайн: вариант A или B? Есть ли макеты/брендбук?
14. Английская версия реально используется? (сейчас 71 инлайновый тернарник вместо словарей)

**Организационные:**

15. Будет ли отдельный staging-сервер? Для платежей и escrow крайне желателен.
16. Есть ли дамп боевой БД для проверки миграций?
17. Подтвердите, что после переезда на чистый сервер все секреты ротированы, а `authorized_keys` проверен.
18. Порядок релизов (см. ниже) — согласуем?

---

# ЧАСТЬ VII. ПОРЯДОК РЕЛИЗОВ

Не «всё сразу в конце», а четыре поставки — так заказчик видит прогресс, а риск ловится рано.

| Релиз | Содержание | Что получает заказчик |
|---|---|---|
| **R1** | Этапы 0, 1, 2 | Закрытые дыры безопасности, порядок в БД, финансовое ядро. Внешне почти без изменений, но проект перестаёт быть опасным |
| **R2** | Этап 3 | Оплата через TON Connect, CryptoBot убран. Главная функциональная цель |
| **R3** | Этап 4 + часть 7 | Подписки на закрытые каналы работают, админка умеет их вести |
| **R4** | Этапы 5, 6, 7, 8 | P2P с escrow, настраиваемая рефералка, полная админка, обновлённый дизайн |

R1 и R2 можно выкатывать быстро — они не требуют решений заказчика по спорным вопросам (кроме курса). R3 и R4 упираются в ответы из части VI.

---

# ЧАСТЬ VIII. ВНУТРЕННЯЯ ОЦЕНКА ТРУДОЁМКОСТИ

> Для собственного планирования, не для клиента.

| Этап | Дни | Сложность |
|---|---|---|
| 0. Безопасность | 1–1.5 | средняя |
| 1. Миграции baseline | 1–1.5 | средняя |
| 2. Финансовый слой | 2.5–3 | высокая |
| 3. TON Connect | 7–9 | высокая |
| 4. Подписки | 7–8 | высокая |
| 5. P2P + escrow + чат сделки | 9–12 | **очень высокая** |
| 6. Настраиваемая рефералка | 1.5–2 | средняя |
| 7. Админка | 5–6 | средняя |
| 8. Дизайн (A / B) | 3–4 / 6–8 | средняя |
| 9. Тесты, доки, приёмка | 2–3 | средняя |
| **Итого** | **40–48 (A) / 43–52 (B)** | |

Ориентир: **8–10 недель** одним разработчиком при полной занятости. Этапы 7 и 8 не пересекаются по файлам с 3–5 и параллелятся вторым исполнителем — это сокращает календарный срок примерно до 6–7 недель.

**Замечание по объёму:** относительно первоначальной оценки (4 задачи, ~2 недели) объём вырос примерно вдвое — добавились P2P-маркетплейс с escrow и чатом сделок, настраиваемая рефералка, условия площадки с фиксацией согласий и финансовый слой под всё это. Стоит либо разнести на два договора по релизам (R1+R2, затем R3+R4), либо заранее проговорить срок, чтобы не было расхождения ожиданий.
