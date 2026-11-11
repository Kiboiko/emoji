"""Owner-only TON Connect invoices for product promotion."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.promotion import PromotionInvoice
from models.user import User
from services import promotion_service, settings_service, terms_service, ton_service
from utils.auth import get_current_user

router = APIRouter(prefix="/api/promotions", tags=["Promotions"])


@router.get("/config")
async def config(db: AsyncSession = Depends(get_db)):
    price = await settings_service.get_int(db, "promotion_price_nano")
    return {
        "price_nano": str(price), "price_ton": str(Decimal(price) / ton_service.NANO),
        "duration_hours": await settings_service.get_int(db, "promotion_duration_hours"),
        "network": "testnet" if settings.ton_is_testnet else "mainnet",
        "manifest_url": ton_service.manifest_url(),
        "receiving_address": settings.TON_RECEIVING_ADDRESS or None,
    }


@router.post("/products/{product_id}/invoice")
async def create(product_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await terms_service.require(db, user, accepted_now=False, context="promotion")
        invoice = await promotion_service.create_invoice(db, product_id, user)
        await db.commit()
        return promotion_service.serialize(invoice)
    except terms_service.TermsNotAccepted as exc:
        raise HTTPException(400, detail={"code": "terms_required", "version": exc.version})
    except promotion_service.PromotionError as exc:
        raise HTTPException(400, detail=str(exc))
    except ton_service.TonError:
        raise HTTPException(503, detail="Payments are not configured")


@router.get("/{invoice_id}/check")
async def check(invoice_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    invoice = await db.get(PromotionInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(404, detail="Invoice not found")
    if invoice.user_id != user.id:
        raise HTTPException(403, detail="Access denied")
    try:
        invoice = await promotion_service.verify_invoice(db, invoice.id)
        await db.commit()
        return promotion_service.serialize(invoice)
    except ton_service.TonError:
        raise HTTPException(503, detail="Payment provider is unavailable")
    except promotion_service.PromotionError as exc:
        raise HTTPException(409, detail=str(exc))
