from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
import logging

from config import settings
from database import engine

# Импорт всех моделей: нужен, чтобы SQLAlchemy успела зарегистрировать мапперы
# до первого обращения (строковые ссылки в relationship разрешаются только
# среди импортированных классов).
from models import *

# Import routers
from routes import auth, products, categories, cart, orders, payments, reviews, users, admin_auth, admin_stats, admin_orders, withdrawals


from services.scheduler import start_scheduler, shutdown_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _read_db_revision(sync_conn):
    from alembic.runtime.migration import MigrationContext
    return MigrationContext.configure(sync_conn).get_current_revision()


async def _verify_schema_is_current() -> None:
    """
    Проверяет, что накатаны все миграции.

    Раньше схему молча досоздавал create_all(), и рассинхрон БД с кодом
    обнаруживался уже в бою, случайной ошибкой в рантайме. Лучше не стартовать
    вовсе и сказать, что делать.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(Path(__file__).parent / "alembic.ini")))
    expected = script.get_current_head()

    async with engine.connect() as conn:
        actual = await conn.run_sync(_read_db_revision)

    if actual == expected:
        logger.info("Схема БД актуальна (revision %s)", actual)
        return

    raise RuntimeError(
        f"Схема БД не соответствует коду: в базе revision={actual or 'отсутствует'}, "
        f"ожидается {expected}. Выполните `alembic upgrade head` перед запуском."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager"""
    # Startup
    # Create upload directories
    upload_dir = Path(settings.UPLOAD_DIR)
    (upload_dir / "products").mkdir(parents=True, exist_ok=True)
    
    # Схема БД управляется ТОЛЬКО Alembic: `alembic upgrade head`.
    #
    # Здесь раньше вызывался Base.metadata.create_all(). Из-за него три таблицы
    # (digital_items, payments, withdrawals) жили без единой миграции, история
    # Alembic разошлась с реальной схемой, а autogenerate начал предлагать
    # удаление колонок. Создание таблиц в обход миграций возвращает эту
    # проблему, поэтому вызов убран намеренно — не возвращать.
    #
    # Вместо молчаливого создания таблиц проверяем, что миграции накатаны,
    # и падаем на старте с внятной ошибкой, если нет.
    await _verify_schema_is_current()

    # Start background scheduler
    start_scheduler()
    
    yield
    
    # Shutdown
    shutdown_scheduler()
    await engine.dispose()


app = FastAPI(
    title="Marketplace 2.0 API",
    version="1.0.0",
    description="Crypto Marketplace API with CryptoBot payments",
    lifespan=lifespan
)

# CORS Configuration
origins = settings.CORS_ORIGINS.copy()
if settings.SITE_URL not in origins:
    origins.append(settings.SITE_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=3600,
)

# Mount static files for uploads
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

from fastapi import WebSocket, WebSocketDisconnect
from utils.websockets import manager

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    print(f"[WS] Connection attempt - token present: {token is not None}")
    user_id = None
    if token:
        try:
            from utils.auth import decode_access_token
            payload = decode_access_token(token)
            user_id = payload.get("user_id")
            print(f"[WS] Decoded token - user_id: {user_id}")
        except Exception as e:
            print(f"[WS] Token decode error: {e}")
            pass
            
    if not user_id:
        print(f"[WS] Rejecting connection - no valid user_id")
        await websocket.close(code=1008)
        return

    print(f"[WS] Accepting connection for user: {user_id}")

    await manager.connect(websocket, user_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)

# Include routers
# Include routers
app.include_router(admin_auth.router)
app.include_router(admin_stats.router)
app.include_router(admin_orders.router)
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(categories.router)
app.include_router(cart.router)
app.include_router(orders.router)
app.include_router(payments.router, prefix="/api")
app.include_router(reviews.router)
app.include_router(users.router)
app.include_router(withdrawals.router)

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Marketplace 2.0 API is running",
        "version": "1.0.0",
        "docs": "/docs"
    }

# Health check
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "app_name": settings.APP_NAME
    }

