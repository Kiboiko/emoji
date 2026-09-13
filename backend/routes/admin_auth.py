from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.user import User
from utils.auth import create_access_token, create_refresh_token, decode_refresh_token, verify_password
from schemas.auth import AdminLogin, TokenResponse
from config import settings
from datetime import timedelta
import uuid

# Define router with /api/admin/auth prefix
router = APIRouter(prefix="/api/admin/auth", tags=["Admin Auth"])

@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: AdminLogin,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    # Find user by username
    result = await db.execute(select(User).where(User.username == login_data.username))
    user = result.scalars().first()

    # 1. Try DB Authentication first (Hashed Password)
    if user and user.hashed_password and verify_password(login_data.password, user.hashed_password):
        pass # Auth successful, user is set
    
    # 2. Try Env-based Authentication (Bootstrap/Recovery)
    elif (login_data.username == settings.ADMIN_USERNAME and 
          login_data.password == settings.ADMIN_PASSWORD):
        
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
        secure=True,  # Production is HTTPS
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
        # Debug print
        print("DEBUG: Refresh token cookie is MISSING in request")
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
        print(f"DEBUG: Refresh token invalid: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid refresh token: {str(e)}"
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
