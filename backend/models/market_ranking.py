import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Integer, BigInteger, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class RankingPeriod(Base):
    __tablename__ = "market_ranking_periods"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    start_at: Mapped[datetime] = mapped_column(DateTime, unique=True, nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    formula_version: Mapped[str] = mapped_column(String(30), default="volume70_review30_v1", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)


class RankingEntry(Base):
    __tablename__ = "market_ranking_entries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("market_ranking_periods.id", ondelete="RESTRICT"), index=True)
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("seller_profiles.id", ondelete="RESTRICT"))
    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    volume_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    sales_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_sum: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quality: Mapped[Decimal] = mapped_column(Numeric(18, 9), default=0, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(18, 9), default=0, nullable=False)
    __table_args__ = (UniqueConstraint("period_id", "seller_id"),)
