from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.market_ranking import RankingPeriod
from models.p2p import SellerProfile
from models.user import User
from services import market_ranking_service as ranking, audit_service
from utils.auth import require_admin

router = APIRouter(prefix="/api/market-rankings", tags=["Market rankings"])
admin_router = APIRouter(prefix="/api/admin/market-rankings", tags=["Admin rankings"])


@router.get("/current")
async def current(db: AsyncSession = Depends(get_db)):
    return await ranking.projection(db, await ranking.current_period(db))


@router.get("/periods")
async def periods(skip: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(RankingPeriod).where(RankingPeriod.status == "closed")
        .order_by(RankingPeriod.start_at.desc()).offset(skip).limit(20))).all()
    return [{"id": str(p.id), "start_at": ranking.iso(p.start_at), "end_at": ranking.iso(p.end_at)} for p in rows]


@router.get("/periods/{period_id}")
async def period(period_id: UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(RankingPeriod, period_id)
    if row is None:
        raise HTTPException(404, "Период не найден")
    return await ranking.projection(db, row)


@admin_router.get("")
async def management(skip: int = Query(0, ge=0), admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    sellers = (await db.scalars(select(SellerProfile).order_by(SellerProfile.created_at, SellerProfile.id).offset(skip).limit(100))).all()
    return {"ranking": await ranking.projection(db, await ranking.current_period(db), admin=True),
        "sellers": [{"id": str(s.id), "name": s.display_name, "home_visible": s.home_visible,
                     "ranking_enabled": s.ranking_enabled, "is_platform": s.is_platform} for s in sellers]}


class Placement(BaseModel):
    home_visible: bool | None = None
    ranking_enabled: bool | None = None


@admin_router.patch("/sellers/{seller_id}")
async def seller_placement(seller_id: UUID, body: Placement, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    seller = await db.get(SellerProfile, seller_id)
    if seller is None:
        raise HTTPException(404, "Магазин не найден")
    if seller.is_platform and body.ranking_enabled:
        raise HTTPException(422, "Площадка не участвует в рейтинге")
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(seller, key, value)
    audit_service.log_action(db, admin, "ranking.placement", target_type="seller", target_id=seller.id, details=changes)
    await db.commit()
    return {"saved": True}


@admin_router.post("/refresh")
async def recalculate(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    period = await ranking.refresh(db)
    audit_service.log_action(db, admin, "ranking.refresh")
    await db.commit()
    return await ranking.projection(db, period, admin=True)
