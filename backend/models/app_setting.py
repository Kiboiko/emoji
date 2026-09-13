import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AppSetting(Base):
    """
    Настройки, редактируемые через админку без передеплоя.

    Сюда переезжает всё, что заказчик должен менять сам: проценты комиссий и
    рефералки, пороги антифрода, сроки. Раньше, например, реферальный процент
    был зашит в REFERRAL_PERCENTAGE в .env — поменять его означало править файл
    на сервере и перезапускать контейнер.

    Значения из этой таблицы ПЕРЕКРЫВАЮТ одноимённые дефолты из кода
    (см. services/settings_service.py). Отсутствие ключа — не ошибка:
    берётся дефолт.
    """
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    # JSONB, а не строка: настройки бывают числом, флагом и списком
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    updated_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<AppSetting({self.key}={self.value})>"
