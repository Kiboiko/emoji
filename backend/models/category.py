import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Integer, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class Category(Base):
    __tablename__ = "categories"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    __table_args__ = (CheckConstraint("parent_id <> id", name="ck_categories_not_self_parent"),)

    # Deleting a category must never delete its products.
    products: Mapped[list["Product"]] = relationship("Product", back_populates="category", passive_deletes="all")
    
    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name_ru={self.name_ru}, name_en={self.name_en})>"
