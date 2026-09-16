from fastapi import APIRouter, Depends, HTTPException, Header, Body, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from database import get_db
from models.user import User
from schemas.user import UserResponse
from utils.auth import validate_telegram_webapp_data, create_access_token, generate_referral_code, get_current_user
from pydantic import BaseModel

from config import settings

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

class AdminLoginRequest(BaseModel):
    username: str
    password: str

@router.post("/admin", response_model=dict)
async def authenticate_admin(
    login_data: AdminLoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Admin authentication via username/password from .env
    """
    if (login_data.username != settings.ADMIN_USERNAME or 
        login_data.password != settings.ADMIN_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials"
        )
    
    # Create or update admin user in DB to ensure relationships work
    # We use a special reserved ID for the main admin
    ADMIN_TELEGRAM_ID = 777000 # Reserved ID
    
    stmt = select(User).where(User.telegram_id == ADMIN_TELEGRAM_ID)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
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
    else:
        # Ensure admin status
        user.is_admin = True
        
    await db.commit()
    await db.refresh(user)
    
    access_token = create_access_token(
        data={
            "user_id": str(user.id),
            "telegram_id": user.telegram_id,
            "is_admin": True
        }
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user)
    }

async def _authenticate_dev_impl(db: AsyncSession):
    """
    Служебная авторизация для локальной разработки: выдаёт админский токен
    без пароля.

    Роут регистрируется ТОЛЬКО при DEBUG=True (см. регистрацию ниже). Раньше
    проверка делалась внутри обработчика, а DEBUG по умолчанию был True и в
    .env не задавался — из-за чего на проде любой мог получить админский токен
    запросом POST /api/auth/dev. Теперь при DEBUG=False эндпоинта не существует
    вовсе и он отдаёт 404.
    """
    # Create or get dev user
    stmt = select(User).where(User.telegram_id == 123456789)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(
            id=uuid.uuid4(),
            telegram_id=123456789,
            username="dev_user",
            first_name="Developer",
            language_code="ru",
            referral_code=generate_referral_code()
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    
    access_token = create_access_token(
        data={
            "user_id": str(user.id),
            "telegram_id": user.telegram_id,
            "is_admin": True  # Dev user is admin
        }
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user)
    }


if settings.DEBUG:
    # Регистрируем dev-вход только в режиме разработки.
    @router.post("/dev", response_model=dict)
    async def authenticate_dev(db: AsyncSession = Depends(get_db)):
        """Development authentication endpoint. Доступен только при DEBUG=True."""
        return await _authenticate_dev_impl(db)


@router.post("/telegram", response_model=dict)
async def authenticate_telegram(
    init_data: str = Header(..., alias="X-Telegram-Init-Data"),
    referral_code: str = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user via Telegram WebApp initData
    Returns access token and user info
    """
    try:
        # Validate Telegram data
        telegram_data = validate_telegram_webapp_data(init_data)
        
        # Check if user exists
        stmt = select(User).where(User.telegram_id == telegram_data["telegram_id"])
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            # Заблокированному токен не выдаём. Проверка именно здесь, до
            # обновления данных: иначе блокировка обходилась бы простым
            # перезаходом в приложение — токен выдавался заново, а проверка
            # is_blocked стоит только на уже выданном токене.
            if user.is_blocked:
                raise HTTPException(
                    status_code=403,
                    detail="Аккаунт заблокирован. Обратитесь в поддержку.",
                )

            # Update user data from Telegram (name/username may have changed)
            user.first_name = telegram_data["first_name"]
            user.username = telegram_data.get("username")
            await db.commit()
            await db.refresh(user)

        if not user:
            # Create new user
            # Use telegram_id as referral code (as string)
            new_referral_code = str(telegram_data["telegram_id"])
            
            print(f"[AUTH] Registering new user: {telegram_data.get('username') or telegram_data['telegram_id']}")
            print(f"[AUTH] Received referral_code from frontend: '{referral_code}'")
            
            # Check if referral code was provided and find referrer
            referrer = None
            if referral_code:
                # First try to find by referral_code (which is now telegram_id string)
                stmt = select(User).where(User.referral_code == referral_code)
                result = await db.execute(stmt)
                referrer = result.scalar_one_or_none()
                
                # If not found, try to find by telegram_id (backward compatibility or direct ID match)
                if not referrer and referral_code.isdigit():
                    try:
                       stmt = select(User).where(User.telegram_id == int(referral_code))
                       result = await db.execute(stmt)
                       referrer = result.scalar_one_or_none()
                    except ValueError:
                       pass

                if referrer:
                    print(f"[AUTH] Found referrer: {referrer.username} (ID: {referrer.id})")
                else:
                    print(f"[AUTH] Referrer NOT found for code: {referral_code}")
            
            user = User(
                id=uuid.uuid4(),
                telegram_id=telegram_data["telegram_id"],
                username=telegram_data.get("username"),
                first_name=telegram_data["first_name"],
                language_code=telegram_data.get("language_code", "ru"),
                referral_code=new_referral_code,
                referrer_id=referrer.id if referrer else None
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"[AUTH] User created. Referrer ID set to: {user.referrer_id}")
        
        # Create access token
        access_token = create_access_token(
            data={
                "user_id": str(user.id),
                "telegram_id": user.telegram_id,
                "is_admin": user.is_admin
            }
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": UserResponse.model_validate(user)
        }
    
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        print(f"DEBUG: Auth failed: {e}")
        raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    user: User = Depends(get_current_user)
):
    """Get current authenticated user"""
    return UserResponse.model_validate(user)

