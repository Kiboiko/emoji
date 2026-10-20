from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select
from database import get_db
from models.user import User
from services import audit_service
from utils.auth import (
    create_access_token, create_refresh_token, decode_refresh_token, get_password_hash,
    require_staff, verify_password,
)
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

# Служебная учётка администратора, которую заводит вход по паролю из .env
ADMIN_TELEGRAM_ID = 777000

MIN_PASSWORD_LENGTH = 10
# bcrypt принимает не больше 72 байт: длиннее он отвергает (в новых версиях)
# или молча обрезает (в старых), и «длинный» пароль на деле короче
MAX_PASSWORD_BYTES = 72


# Простейший in-memory лимитер попыток входа: {ip: [timestamp, ...]}.
# Достаточно для одного инстанса; при масштабировании вынести в Redis.
_login_attempts: dict[str, list[float]] = defaultdict(list)
# Когда с адреса последний раз записали отказ «слишком много попыток»
_rate_limited_logged: dict[str, float] = {}


def _client_ip(request: Request) -> str:
    """
    Адрес человека, а не соседнего контейнера.

    Перед бэкендом стоят Caddy и nginx, и request.client.host — это адрес
    nginx: один на всех. Лимит попыток тогда был общим на всех админов, и
    несколько человек вместе упирались в «слишком много попыток» с верным
    паролем. Первая запись X-Forwarded-For ставится Caddy из реального
    соединения; наружу бэкенд и nginx напрямую не открыты, подделать её
    с улицы нельзя.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


def _is_rate_limited(client_ip: str) -> bool:
    """Было ли с адреса слишком много НЕУДАЧНЫХ попыток за окно."""
    now = time.time()
    window = settings.LOGIN_ATTEMPT_WINDOW_SECONDS
    attempts = [t for t in _login_attempts[client_ip] if now - t < window]
    _login_attempts[client_ip] = attempts
    if len(attempts) >= settings.LOGIN_MAX_ATTEMPTS:
        logger.warning("[ADMIN AUTH] Превышен лимит попыток входа с IP %s", client_ip)
        return True
    return False


def _register_failed_attempt(client_ip: str) -> None:
    # Успешный вход попытку не тратит: иначе несколько нормальных входов
    # подряд (вышел, зашёл) блокировали бы правильный пароль
    _login_attempts[client_ip].append(time.time())


def validate_new_password(password: str, username: str | None = None) -> None:
    """Требования к новому паролю персонала. 400 с понятным текстом."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Пароль слишком короткий: нужно не меньше {MIN_PASSWORD_LENGTH} символов",
        )
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Пароль слишком длинный: не больше {MAX_PASSWORD_BYTES} байт",
        )
    if len(set(password)) < 5:
        raise HTTPException(status_code=400, detail="Пароль слишком простой: больше разных символов")
    if username and password.lower() == username.lower():
        raise HTTPException(status_code=400, detail="Пароль не должен совпадать с логином")


def _role(user: User) -> str:
    return "admin" if user.is_admin else "moderator"


def _issue_access_token(user: User) -> str:
    return create_access_token(
        data={
            "user_id": str(user.id),
            "sub": user.username,
            # is_admin — только у администратора: админка по нему решает, какие
            # разделы показывать, а бэкенд — какие маршруты открывать
            "is_admin": bool(user.is_admin),
            "role": _role(user),
            "tv": int(user.token_version or 0),
        },
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def _set_refresh_cookie(response: Response, user: User) -> None:
    refresh_token = create_refresh_token(
        data={
            "user_id": str(user.id), "sub": user.username, "type": "refresh",
            "tv": int(user.token_version or 0),
        }
    )
    response.set_cookie(
        key="admin_refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,  # False для локальной разработки по HTTP
        samesite="lax",
        path="/",
        max_age=7 * 24 * 60 * 60,  # 7 days
    )


def _env_password_matches(username: str, password: str) -> bool:
    # Сравнение постоянного времени — обычный == по паролю утекает информацию
    # через тайминги и позволяет подбирать пароль посимвольно.
    return (
        hmac.compare_digest(username.encode(), settings.ADMIN_USERNAME.encode())
        and hmac.compare_digest(password.encode(), settings.ADMIN_PASSWORD.encode())
    )


async def _fail_login(
    db: AsyncSession, request: Request, username: str, reason: str,
    user: User | None = None, *, count: bool = True,
) -> None:
    """Журналит неудачную попытку и отвечает 401 (или 429 для лимита)."""
    ip = _client_ip(request)
    if count:
        _register_failed_attempt(ip)
    # Отказы по лимиту пишем раз за окно с адреса, а не на каждый запрос:
    # поток запросов от одного адреса иначе без конца раздувал бы журнал, а
    # одной записи достаточно, чтобы увидеть перебор
    now = time.time()
    if reason != "rate_limited" or now - _rate_limited_logged.get(ip, 0.0) >= settings.LOGIN_ATTEMPT_WINDOW_SECONDS:
        if reason == "rate_limited":
            _rate_limited_logged[ip] = now
        audit_service.log_login(
            db, username=username, success=False, reason=reason, ip=ip,
            user_agent=request.headers.get("user-agent"), user=user,
        )
    # Явный коммит: get_db откатывает сессию при исключении, и запись о
    # неудачной попытке пропала бы вместе с ней — а нужна она именно тогда
    await db.commit()
    if reason == "rate_limited":
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts, try again later",
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: AdminLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    username = login_data.username.strip()
    client_ip = _client_ip(request)

    if _is_rate_limited(client_ip):
        await _fail_login(db, request, username, "rate_limited", count=False)

    # Войти в админку может только персонал. Фильтр по роли здесь, а не после:
    # у обычного пользователя приложения может совпасть @username с логином
    # модератора, и пароль проверялся бы не у той учётки
    user = (
        await db.execute(
            select(User)
            .where(User.username == username, or_(User.is_admin, User.is_moderator))
            .order_by(User.is_admin.desc())
            .limit(1)
        )
    ).scalars().first()

    if user is not None and user.hashed_password:
        # 1. Пароль в базе. Если он задан, пароль из .env больше НЕ действует:
        # иначе смена пароля в админке ничего бы не закрывала — старый
        # продолжал бы работать
        if not verify_password(login_data.password, user.hashed_password):
            await _fail_login(db, request, username, "bad_password", user)
        if user.is_blocked:
            await _fail_login(db, request, username, "blocked", user)
    elif (user is not None and user.is_admin) or (
        user is None and hmac.compare_digest(username.encode(), settings.ADMIN_USERNAME.encode())
    ):
        # 2. Пароль из .env (первый вход и восстановление): работает, пока в
        # базе у администратора нет своего. Восстановление доступа — очистить
        # hashed_password у учётки админа, и снова действует пароль из .env
        if not _env_password_matches(username, login_data.password):
            await _fail_login(db, request, username, "bad_password", user)

        if user is None:
            # Учётки может не быть вовсе (новая база) — заводим служебную
            user = (
                await db.execute(select(User).where(User.telegram_id == ADMIN_TELEGRAM_ID))
            ).scalars().first()
            if user is not None:
                user.username = settings.ADMIN_USERNAME
            else:
                user = User(
                    id=uuid.uuid4(),
                    telegram_id=ADMIN_TELEGRAM_ID,
                    username=settings.ADMIN_USERNAME,
                    first_name="Administrator",
                    language_code="en",
                    is_admin=True,
                    referral_code="admin",
                )
                db.add(user)
        if user.is_blocked:
            await _fail_login(db, request, username, "blocked", user)
        user.is_admin = True
        await db.flush()
    else:
        # Нет такого логина или у модератора нет пароля в базе
        await _fail_login(db, request, username, "unknown_user")

    audit_service.log_login(
        db, username=username, success=True, reason="ok", ip=client_ip,
        user_agent=request.headers.get("user-agent"), user=user,
    )
    await db.commit()

    _set_refresh_cookie(response, user)
    return {"access_token": _issue_access_token(user), "token_type": "bearer", "role": _role(user)}


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

    # Check if user still exists and still has access
    user = await db.get(User, uuid.UUID(user_id))
    revoked = (
        user is not None
        and int(payload.get("tv", 0)) != int(user.token_version or 0)
    )
    if (
        not user or revoked or user.is_blocked
        or not (user.is_admin or user.is_moderator)
    ):
        # Clear cookie if invalid
        response.delete_cookie("admin_refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User invalid or missing privileges"
        )

    return {"access_token": _issue_access_token(user), "token_type": "bearer", "role": _role(user)}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("admin_refresh_token")
    return {"message": "Logged out successfully"}


@router.get("/me")
async def me(user: User = Depends(require_staff)):
    return {"id": str(user.id), "username": user.username, "role": _role(user)}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
async def change_password(
    payload: PasswordChange,
    response: Response,
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    Смена своего пароля.

    После неё завершаются ВСЕ сессии этой учётки, включая текущую: токены
    живут неделю, и украденный иначе оставался бы рабочим. Входить нужно
    заново с новым паролем.
    """
    if user.hashed_password:
        current_ok = verify_password(payload.current_password, user.hashed_password)
    else:
        # Пароля в базе ещё нет — действует пароль из .env
        current_ok = _env_password_matches(user.username or "", payload.current_password)
    if not current_ok:
        raise HTTPException(status_code=400, detail="Текущий пароль неверный")

    validate_new_password(payload.new_password, user.username)
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="Новый пароль должен отличаться от текущего")

    user.hashed_password = get_password_hash(payload.new_password)
    user.token_version = int(user.token_version or 0) + 1
    audit_service.log_action(db, user, "auth.password_changed", target_type="user", target_id=user.id)
    await db.commit()

    response.delete_cookie("admin_refresh_token")
    return {"message": "Пароль изменён. Войдите заново."}


@router.post("/logout-all")
async def logout_all(
    response: Response,
    user: User = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    """
    «Выйти везде»: сброс всех токенов этой учётки, включая текущий.

    Нужен, если токен мог утечь или админку открывали на чужом устройстве.
    """
    user.token_version = int(user.token_version or 0) + 1
    audit_service.log_action(db, user, "auth.sessions_reset", target_type="user", target_id=user.id)
    await db.commit()

    response.delete_cookie("admin_refresh_token")
    return {"message": "Все сессии завершены. Войдите заново."}
