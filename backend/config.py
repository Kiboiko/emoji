from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://marketplace_user:changeme@127.0.0.1:5432/marketplace"
    
    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    REVIEWS_CHANNEL_ID: str = ""
    ADMIN_CHAT_ID: str = ""
    
    # CryptoBot
    CRYPTOBOT_API_TOKEN: str = ""
    CRYPTOBOT_TESTNET: bool = True
    
    # Application
    APP_NAME: str = "Marketplace 2.0"
    SITE_URL: str = "http://localhost:3000"
    DEBUG: bool = True
    
    # Admin Credentials
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "change_me"
    
    # File uploads
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 5 * 1024 * 1024  # 5MB
    
    # Referral system
    REFERRAL_PERCENTAGE: float = 3.0  # 3%
    
    # CORS Origins
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
