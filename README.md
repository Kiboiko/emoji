# Marketplace 2.0

Telegram Mini App — маркетплейс цифровых товаров.

| Слой | Стек |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 17, Alembic, APScheduler |
| Витрина | React 19, TypeScript, Vite, zustand, framer-motion |
| Админка | React 19, TypeScript, Vite, TanStack Query, Tailwind 4 |
| Бот | aiogram 3 |
| Инфра | Docker Compose, nginx |

---

## Запуск локально

Нужен Docker с Compose v2.

```bash
cp .env.example .env
# заполнить DB_PASSWORD, SECRET_KEY, ADMIN_PASSWORD
# для локального запуска обязательно: DEBUG=true, COOKIE_SECURE=false
```

```bash
docker compose up -d postgres
docker compose run --rm backend alembic upgrade head   # обязательно до первого старта
docker compose up -d
```

| Что | Адрес |
|---|---|
| Витрина | http://localhost:8080/ |
| Админка | http://localhost:8080/admin/ |
| API | http://localhost:8080/api/ |
| Swagger | http://localhost:8000/docs (порт проброшен только локально) |
| PostgreSQL | `localhost:5433` |

Демо-данные: `docker compose exec backend python seed.py`

### Тесты

```bash
docker compose exec postgres psql -U marketplace_user -d postgres -c "CREATE DATABASE marketplace_test;"
docker compose exec backend python -m pytest -q
```

Тесты работают с отдельной базой (`<имя_базы>_test`), схема создаётся из моделей. Переопределяется переменной `TEST_DATABASE_URL`.

Сервис `bot` требует `TELEGRAM_BOT_TOKEN` и без него не поднимается. Для локальной работы заведите **отдельного тестового бота** — боевой и локальный не могут читать апдейты одновременно.

Витрина открывается только внутри Telegram: без `initData` она показывает «Откройте через Telegram». Админка работает в обычном браузере.

### Локальный оверрайд

`docker-compose.override.yml` подхватывается автоматически и включает: монтирование кода backend внутрь контейнера (правки без пересборки), `--reload`, проброс порта 8000.

**На боевом сервере его быть не должно.** Запуск в проде — с явным указанием файла:

```bash
docker compose -f docker-compose.yml up -d
```

---

## Миграции

Схема управляется **только** Alembic. `Base.metadata.create_all()` намеренно убран: из-за него часть таблиц жила без миграций и история Alembic разошлась со схемой (см. `docs/STAGE-1-REPORT.md`).

Приложение проверяет на старте, что revision в базе совпадает с head, и **не стартует** при расхождении.

```bash
docker compose run --rm backend alembic upgrade head      # применить
docker compose run --rm backend alembic current           # текущая ревизия
docker compose run --rm backend alembic revision --autogenerate -m "описание"
```

> Автосгенерированную миграцию **всегда читать глазами** перед применением. Проект достался с расхождениями модель↔БД; они устранены, но привычка обязательна: одна невнимательная миграция может снести колонку или поменять каскадное удаление.

Порядок выкатки на прод:

```bash
docker compose -f docker-compose.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.yml up -d
```

---

## Переменные окружения

Полный список с комментариями — в `.env.example`. Критичные:

| Переменная | Прод | Смысл |
|---|---|---|
| `DEBUG` | **`false`** | При `true` регистрируется `POST /api/auth/dev`, выдающий админский токен **без пароля** |
| `COOKIE_SECURE` | `true` | Флаг Secure у cookie админки. Локально по HTTP — `false`, иначе вход не работает |
| `SQL_ECHO` | `false` | Вывод всех SQL-запросов в лог |
| `SECRET_KEY` | случайный | Подпись JWT |
| `TON_NETWORK` | `mainnet` | Сеть TON. Сейчас настроен `testnet` |
| `TON_RECEIVING_ADDRESS` | адрес кошелька | Куда приходят платежи. Пусто — приём оплаты отдаёт 503 |
| `TON_API_KEY` | ключ toncenter | Без него лимит ~1 запрос/сек |

### Оплата в TON

Курс, срок его фиксации и время жизни счёта настраиваются **в админке**
(`ton_rate_source`, `ton_rate_ttl_sec`, `order_payment_ttl_min`), а не в `.env`.

Манифест TON Connect генерируется на сборке образа из `SITE_URL`. Кошелёк
скачивает его сам и сверяет origin, поэтому **с localhost полный прогон оплаты
невозможен** — нужен публичный HTTPS-домен.

`.env` в git не попадает. Секреты из архива предыдущего разработчика считать скомпрометированными.

---

## Документация

| Файл | Что внутри |
|---|---|
| `WORK_PLAN.md` | План работ по этапам, целевые схемы данных, ограничения Telegram Bot API |
| `ESTIMATE.md` | Аудит доставшегося кода, карта архитектуры, риски |
| `docs/STAGE-0-REPORT.md` | Фиксы безопасности, аудит роутов |
| `docs/STAGE-1-REPORT.md` | Приведение миграций в порядок |
| `docs/STAGE-2-REPORT.md` | Финансовый слой: счета, журнал, сверка, настройки |
| `docs/STAGE-3-REPORT.md` | Оплата в TON через TON Connect |
| `docs/db/` | Дампы схемы: до и после этапа 1 |

---

## Структура

```
backend/
  main.py          точка входа, lifespan, WebSocket /ws, проверка схемы БД
  config.py        настройки из .env
  models/          SQLAlchemy-модели (полный реестр в __init__.py)
  schemas/         Pydantic-схемы
  routes/          эндпоинты
  services/        деньги (money, finance), настройки, платежи, Telegram,
                   рефералы, планировщик
  tests/           pytest: денежная арифметика и финансовый слой
  utils/           JWT, валидация Telegram initData, WebSocket-менеджер
  alembic/         миграции
frontend/          витрина
admin/             админ-панель
bot/               Telegram-бот
nginx/             reverse-proxy, раздача статики
```
