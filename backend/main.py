from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path

from config import settings
from database import engine
from database import Base

# Import all models for table creation
from models import *

# Import routers
from routes import auth, products, categories, cart, orders, payments, reviews, users, admin_auth, admin_stats, admin_orders, withdrawals


from services.scheduler import start_scheduler, shutdown_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager"""
    # Startup
    # Create upload directories
    upload_dir = Path(settings.UPLOAD_DIR)
    (upload_dir / "products").mkdir(parents=True, exist_ok=True)
    
    # Create database tables (in production, use Alembic migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
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

