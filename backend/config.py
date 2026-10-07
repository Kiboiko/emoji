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
    
    # --- TON Connect -----------------------------------------------------
    # testnet | mainnet. От этого зависит адрес индексера и сеть кошелька.
    TON_NETWORK: str = "testnet"

    # Кошелёк платформы, на который приходят платежи покупателей.
    # Обязателен для приёма оплаты; при пустом значении инициация платежа
    # отдаёт понятную ошибку, а не молчит.
    TON_RECEIVING_ADDRESS: str = ""

    # Индексер для проверки транзакций. Пусто -> подставляется по TON_NETWORK.
    TON_API_BASE: str = ""
    # Ключ toncenter. Без него работает, но с жёстким лимитом ~1 запрос/сек.
    TON_API_KEY: str = ""

    # Сколько транзакций забирать за один опрос индексера
    TON_TX_FETCH_LIMIT: int = 100
    # Запас по времени при поиске транзакции: платёж мог уйти чуть раньше
    # фиксации курса или подтвердиться заметно позже истечения счёта
    TON_LOOKBACK_SECONDS: int = 300
    TON_LOOKAHEAD_SECONDS: int = 1800

    # Домен для tonconnect-manifest.json (по умолчанию SITE_URL)
    TONCONNECT_MANIFEST_URL: str = ""

    @property
    def ton_api_base(self) -> str:
        if self.TON_API_BASE:
            return self.TON_API_BASE.rstrip("/")
        return (
            "https://testnet.toncenter.com/api/v2"
            if self.TON_NETWORK == "testnet"
            else "https://toncenter.com/api/v2"
        )

    @property
    def ton_is_testnet(self) -> bool:
        return self.TON_NETWORK != "mainnet"
    
    # Application
    APP_NAME: str = "Marketplace 2.0"
    SITE_URL: str = "http://localhost:3000"

    # ВНИМАНИЕ: DEBUG=True регистрирует служебный эндпоинт POST /api/auth/dev,
    # который выдаёт админский токен без пароля. Дефолт обязан быть False,
    # чтобы забытая переменная в .env не открывала админку наружу.
    DEBUG: bool = False

    # Вывод всех SQL-запросов в лог. Отделён от DEBUG: включать точечно при
    # отладке запросов, иначе логи прода забиваются и туда утекают данные.
    SQL_ECHO: bool = False

    # Максимальный возраст Telegram initData. Без этой проверки перехваченный
    # initData работает бессрочно.
    INITDATA_MAX_AGE_SECONDS: int = 86400  # 24 часа

    # Флаг Secure у cookie с refresh-токеном админки. На проде (HTTPS) — True.
    # Локально по HTTP браузер Secure-cookie не сохранит и вход не заработает.
    COOKIE_SECURE: bool = True

    # Простой лимит попыток входа в админку (защита от перебора пароля)
    LOGIN_MAX_ATTEMPTS: int = 10
    LOGIN_ATTEMPT_WINDOW_SECONDS: int = 300

    # Общий секрет для внутреннего API (бот -> бэкенд).
    # Пустое значение НЕ означает "пускать всех": эндпоинты отдают 503.
    INTERNAL_API_TOKEN: str = ""

    # Admin Credentials
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "change_me"
    
    # File uploads
    UPLOAD_DIR: str = "uploads"
    # 20 МБ: снимок с современного телефона весит 8–15 МБ. Хранится не
    # оригинал, а уменьшенная копия (services/image_upload.py). Лимит тела
    # запроса в nginx/nginx.conf должен быть больше этого
    MAX_UPLOAD_SIZE: int = 20 * 1024 * 1024

    # Фото из переписки по сделкам. Отдельно от UPLOAD_DIR: тот целиком
    # раздаётся наружу через nginx, а здесь скриншоты аккаунтов и ключей —
    # они уходят только по подписанной ссылке (services/deal_media.py)
    DEAL_MEDIA_DIR: str = "deal_media"
    DEAL_MEDIA_MAX_SIZE: int = 20 * 1024 * 1024

    # Реферальные проценты переехали в настройки БД (referral_l1_bp) —
    # заказчик меняет их в админке без передеплоя. См. services/settings_service.py
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
