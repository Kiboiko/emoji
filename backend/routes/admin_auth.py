from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.user import User
from utils.auth import create_access_token, create_refresh_token, decode_refresh_token, verify_password
from schemas.auth import AdminLogin, TokenResponse
from config import settings
from datetime import timedelta
from collections import defaultdict
import hmac
import logging
import time
import uuid

logger = logging.getLogger(__name__)

# Define router with /api/admin/auth prefix
router = APIRouter(prefix="/api/admin/auth", tags=["Admin Auth"])


# Простейший in-memory лимитер попыток входа: {ip: [timestamp, ...]}.
# Достаточно для одного инстанса; при масштабировании вынести в Redis.
_login_attempts: dict[str, list[float]] = defaultdict(list)


def _check_login_rate_limit(client_ip: str) -> None:
    now = time.time()
    window = settings.LOGIN_ATTEMPT_WINDOW_SECONDS
    attempts = [t for t in _login_attempts[client_ip] if now - t < window]
    _login_attempts[client_ip] = attempts
    if len(attempts) >= settings.LOGIN_MAX_ATTEMPTS:
        logger.warning("[ADMIN AUTH] Превышен лимит попыток входа с IP %s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts, try again later",
        )
    _login_attempts[client_ip].append(now)


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: AdminLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    _check_login_rate_limit(request.client.host if request.client else "unknown")

    # Find user by username
    result = await db.execute(select(User).where(User.username == login_data.username))
    user = result.scalars().first()

    # 1. Try DB Authentication first (Hashed Password)
    if user and user.hashed_password and verify_password(login_data.password, user.hashed_password):
        pass # Auth successful, user is set
    
    # 2. Try Env-based Authentication (Bootstrap/Recovery)
    # Сравнение постоянного времени — обычный == по паролю утекает информацию
    # через тайминги и позволяет подбирать пароль посимвольно.
    elif (
        hmac.compare_digest(login_data.username, settings.ADMIN_USERNAME)
        and hmac.compare_digest(login_data.password, settings.ADMIN_PASSWORD)
    ):

        # Admin credentials from environment match. 
        # Ensure we have a valid user record in DB.
        
        ADMIN_TELEGRAM_ID = 777000 # Reserved ID for main admin
        
        if not user:
            # Check if user exists by Telegram ID to avoid IntegrityError
            stmt = select(User).where(User.telegram_id == ADMIN_TELEGRAM_ID)
            result = await db.execute(stmt)
            existing_by_tg = result.scalars().first()
            
            if existing_by_tg:
                user = existing_by_tg
                user.username = settings.ADMIN_USERNAME # Update username to match env
            else:
                # Create new admin user
                user = User(
                    id=uuid.uuid4(),
                    telegram_id=ADMIN_TELEGRAM_ID,
                    username=settings.ADMIN_USERNAME,
                    first_name="Administrator",
                    language_code="en",
                    is_admin=True,
                    referral_code="admin"
                )
                db.add(user)
        
        # Ensure admin privileges
        user.is_admin = True
        
        await db.commit()
        await db.refresh(user)
        
    else:
        # Auth failed
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Final checks
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have admin privileges",
        )

    # Create tokens
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"user_id": str(user.id), "sub": user.username, "is_admin": True},
        expires_delta=access_token_expires
    )
    
    refresh_token = create_refresh_token(
        data={"user_id": str(user.id), "sub": user.username, "type": "refresh"}
    )

    # Set Refresh Token in HttpOnly Cookie
    response.set_cookie(
        key="admin_refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,  # False для локальной разработки по HTTP
        samesite="lax",
        path="/",
        max_age=7 * 24 * 60 * 60,  # 7 days
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    refresh_token = request.cookies.get("admin_refresh_token")
    if not refresh_token:
        logger.info("[ADMIN AUTH] Запрос refresh без cookie")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing in cookie"
        )

    try:
        payload = decode_refresh_token(refresh_token)
        user_id = payload.get("user_id")
        if not user_id:
            raise ValueError("Invalid payload: no user_id")
    except Exception as e:
        logger.warning("[ADMIN AUTH] Невалидный refresh-токен: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    # Check if user still exists and is admin
    user = await db.get(User, uuid.UUID(user_id))
    if not user or not user.is_admin:
        # Clear cookie if invalid
        response.delete_cookie("admin_refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User invalid or missing privileges"
        )
        

    # Issue new Access Token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"user_id": str(user.id), "sub": user.username, "is_admin": True},
        expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("admin_refresh_token")
    return {"message": "Logged out successfully"}
