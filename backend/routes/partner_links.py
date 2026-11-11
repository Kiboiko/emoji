from uuid import UUID
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.user import User
from models.partner import PartnerLink, PartnerAttribution, PartnerCommission
from services import partner_service, audit_service
from services.money import from_minor
from config import settings
from utils.auth import require_admin

router = APIRouter(prefix="/api/admin/partner-links", tags=["Partner links"])


class CreateLink(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    telegram_id: int = Field(gt=0, le=9_000_000_000_000_000)


class SetEnabled(BaseModel):
    enabled: bool


async def dto(db, row):
    owner = await db.get(User, row.beneficiary_id)
    invited = await db.scalar(select(func.count()).select_from(PartnerAttribution).where(PartnerAttribution.link_id == row.id))
    accrued = await db.scalar(select(func.coalesce(func.sum(PartnerCommission.amount_nano), 0)).where(PartnerCommission.link_id == row.id))
    bot = settings.VITE_BOT_USERNAME.lstrip("@").strip()
    return {"id":str(row.id), "name":row.name, "code":row.code, "enabled":row.enabled,
        "recipient": owner.first_name if owner else None, "username":owner.username if owner else None,
        "telegram_id":str(owner.telegram_id) if owner else None, "invited":invited,
        "accrued_gram":str(from_minor(int(accrued), "TON")),
        "url":f"https://t.me/{bot}?startapp=ref_{quote(row.code)}" if bot else None}


@router.get("")
async def listing(skip: int = Query(0, ge=0), admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(PartnerLink).order_by(PartnerLink.created_at.desc(), PartnerLink.id).offset(skip).limit(30))).all()
    return [await dto(db, row) for row in rows]


@router.post("")
async def create(body: CreateLink, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    owner = await db.scalar(select(User).where(User.telegram_id == body.telegram_id))
    if owner is None: raise HTTPException(404, "Получатель должен сначала открыть приложение")
    if owner.is_blocked: raise HTTPException(409, "Получатель заблокирован")
    row = PartnerLink(code=partner_service.new_code(), name=body.name.strip(), beneficiary_id=owner.id, created_by=admin.id)
    if not row.name: raise HTTPException(422, "Укажите название ссылки")
    db.add(row); await db.flush()
    audit_service.log_action(db, admin, "partner_link.create", target_type="partner_link", target_id=row.id)
    await db.commit()
    return await dto(db, row)


@router.patch("/{identifier}")
async def enable(identifier: UUID, body: SetEnabled, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(PartnerLink).where(PartnerLink.id == identifier).with_for_update())
    if row is None: raise HTTPException(404, "Ссылка не найдена")
    row.enabled = body.enabled
    audit_service.log_action(db, admin, "partner_link.enable" if body.enabled else "partner_link.disable", target_type="partner_link", target_id=row.id)
    await db.commit()
    return await dto(db, row)
