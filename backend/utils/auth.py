import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from jwt import InvalidTokenError as JWTError
from urllib.parse import parse_qs
from config import settings



from fastapi import HTTPException, Header, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.user import User
import uuid
import bcrypt

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except ValueError:
        # Пароль длиннее 72 байт или битый хеш — это «не подходит», а не
        # ошибка сервера: иначе вход отвечал бы 500 и выдавал причину
        return False

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def _telegram_photo(value) -> str | None:
    from urllib.parse import urlsplit
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and parsed.port in (None, 443):
            return value
    except ValueError:
        pass
    return None


def validate_telegram_webapp_data(init_data: str) -> dict:
    # ... (existing code validation logic) ...
    try:
        # Parse init_data
        parsed_data = parse_qs(init_data)
        
        # Extract hash
        received_hash = parsed_data.get('hash', [''])[0]
        if not received_hash:
            raise ValueError("Hash not found in initData")
        
        # Create data-check-string
        #
        # Исключается ТОЛЬКО hash. Поле signature — отдельная подпись Ed25519,
        # которой Telegram позволяет проверить данные без токена бота, — в
        # расчёт HMAC ВХОДИТ наравне с остальными.
        #
        # Здесь была ошибка: signature исключили из строки, решив по аналогии,
        # что он служебный, — и вход сломался у всех клиентов, которые это поле
        # присылают. Проверено на живом сервере перебором вариантов: сходится
        # только тот, где убран один hash.
        data_check_arr = []
        for key, value in parsed_data.items():
            if key != 'hash':
                data_check_arr.append(f"{key}={value[0]}")
        
        data_check_arr.sort()
        data_check_string = '\n'.join(data_check_arr)
        
        # Create secret key
        secret_key = hmac.new(
            b"WebAppData",
            settings.TELEGRAM_BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        # Calculate hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Verify hash (сравнение постоянного времени — защита от timing-атак)
        if not hmac.compare_digest(calculated_hash, received_hash):
            raise ValueError("Invalid hash")

        # Проверка срока годности initData. Без неё перехваченный initData
        # остаётся валидным бессрочно и позволяет войти за пользователя.
        raw_auth_date = parsed_data.get('auth_date', [''])[0]
        if not raw_auth_date:
            raise ValueError("auth_date not found in initData")
        try:
            auth_date = int(raw_auth_date)
        except ValueError:
            raise ValueError("auth_date is not a valid timestamp")

        age_seconds = datetime.now(timezone.utc).timestamp() - auth_date
        if age_seconds > settings.INITDATA_MAX_AGE_SECONDS:
            raise ValueError("initData expired")
        # Небольшой допуск на расхождение часов между сервером и клиентом
        if age_seconds < -300:
            raise ValueError("initData auth_date is in the future")

        # Parse user data
        import json
        user_data = json.loads(parsed_data.get('user', ['{}'])[0])
        
        return {
            "telegram_id": user_data.get("id"),
            "username": user_data.get("username"),
            "first_name": user_data.get("first_name"),
            "photo_url": _telegram_photo(user_data.get("photo_url")),
            "language_code": user_data.get("language_code", "ru"),
        }
    
    except Exception as e:
        raise ValueError(f"Failed to validate Telegram data: {str(e)}")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=7)  # Refresh tokens live longer (e.g., 7 days)
    
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    
    return encoded_jwt


def decode_refresh_token(token: str) -> dict:
    """Decode and verify JWT refresh token"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "refresh":
            raise ValueError("Invalid token type")
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid token: {str(e)}")


def decode_access_token(token: str) -> dict:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        # Old access tokens have no type; refresh cookies must never act as
        # bearer credentials for ordinary or administrator endpoints.
        if payload.get("type") not in (None, "access"):
            raise ValueError("Invalid token type")
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid token: {str(e)}")


def generate_referral_code(length: int = 8) -> str:
    """Generate unique referral code"""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def token_revoked(payload: dict, user: User) -> bool:
    """
    Отозван ли токен персонала: версия в токене отстала от версии в базе.

    Токены админки несут версию (tv) и перестают действовать при смене пароля
    и «выйти везде». Токен приложения версии не имеет и не проверяется.

    Токен админа, выданный до появления версии, тоже считается токеном
    персонала (is_admin без telegram_id — токены приложения несут
    telegram_id) и сверяется как версия 0: иначе он пережил бы любую смену
    пароля до конца своих семи дней.
    """
    staff_token = "tv" in payload or (payload.get("is_admin") and "telegram_id" not in payload)
    return bool(staff_token) and int(payload.get("tv", 0)) != int(user.token_version or 0)


# === NEW DEPENDENCIES ===

async def get_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependency to get current authenticated user.

    Заголовок объявлен необязательным намеренно. С Header(...) его отсутствие
    даёт 422 «ошибка валидации», а клиенты (и витрина, и админка) считают
    признаком протухшей сессии именно 401 — админка по нему обновляет токен.
    С 422 вместо повторного входа пользователь видел бы непонятную ошибку.
    """
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Extract token
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization header")
        
        token = authorization.replace("Bearer ", "")
        
        # Decode token
        try:
            payload = decode_access_token(token)
        except ValueError as e:
             raise HTTPException(status_code=401, detail=str(e))

        user_id = payload.get("user_id")
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Get user
        user = await db.get(User, uuid.UUID(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Блокировка проверяется здесь, а не в отдельных роутах: колонка
        # is_blocked существовала с первой миграции, но не проверялась нигде,
        # то есть заблокировать человека было невозможно — он продолжал
        # покупать и торговать как ни в чём не бывало.
        #
        # 403, а не 401: 401 клиенты понимают как «сессия истекла» и пробуют
        # перелогиниться, что при блокировке даёт бесконечный цикл.
        if user.is_blocked:
            raise HTTPException(
                status_code=403,
                detail="Аккаунт заблокирован. Обратитесь в поддержку.",
            )

        # Токены персонала (админка) несут версию и перестают действовать,
        # когда она выросла — смена пароля и «выйти везде». Токен приложения
        # версии не имеет и не проверяется.
        #
        # Токен админки, выданный до появления версии, тоже считается токеном
        # персонала (is_admin без telegram_id — токены приложения несут
        # telegram_id) и сверяется как версия 0: иначе он пережил бы любую
        # смену пароля до конца своих семи дней.
        if token_revoked(payload, user):
            raise HTTPException(
                status_code=401, detail="Сессия завершена. Войдите заново.",
            )

        return user
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Только администратор: все разделы админки, кроме общих с модератором."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_staff(user: User = Depends(get_current_user)) -> User:
    """
    Администратор или модератор.

    Нужен там, где работает и модератор: проверка товаров, споры по сделкам,
    удаление фото. Всё остальное закрыто require_admin — модератор с
    флагом is_moderator туда не попадает.
    """
    if not (user.is_admin or user.is_moderator):
        raise HTTPException(status_code=403, detail="Staff access required")
    return user

