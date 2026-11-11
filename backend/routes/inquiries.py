import asyncio
from datetime import datetime
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models.user import User
from models.inquiry import Inquiry, InquiryMessage
from services import inquiry_service as service, deal_media
from utils.auth import get_current_user
from utils.websockets import manager
from config import settings

router = APIRouter(prefix="/api/inquiries", tags=["Seller inquiries"])


@router.get("/store/{store_id}")
async def prepare(store_id: UUID, kind: Literal["seller", "channel"] = "seller", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.prepare(db, store_id, user, kind)


@router.post("/store/{store_id}/messages")
async def first_message(store_id: UUID, kind: Literal["seller", "channel"] = "seller", body: str = Form("", max_length=2000),
                        photo: UploadFile | None = File(None), client_id: UUID | None = Form(None),
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not body.strip() and photo is None:
        raise HTTPException(400, "Введите сообщение или добавьте фото")
    try:
        row = await service.open_chat(db, store_id, user, kind)
        message = await send(row.id, body=body, photo=photo, client_id=client_id, user=user, db=db)
        return {"chat": await service.metadata(db, row, user), "message": message}
    except Exception:
        await db.rollback()
        raise


@router.post("/store/{store_id}")
async def open_inquiry(store_id: UUID, kind: Literal["seller", "channel"] = "seller", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await service.open_chat(db, store_id, user, kind)
    await db.commit()
    return await service.metadata(db, row, user)


@router.get("")
async def listing(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await service.listing(db, user)


@router.get("/{identifier}")
async def detail(identifier: UUID, before: UUID | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await service.own(db, identifier, user)
    stmt = select(InquiryMessage).where(InquiryMessage.inquiry_id == row.id)
    if before:
        cursor = await db.get(InquiryMessage, before)
        if not cursor or cursor.inquiry_id != row.id: raise HTTPException(404, "Сообщение не найдено")
        from sqlalchemy import and_
        stmt = stmt.where(or_(InquiryMessage.created_at < cursor.created_at,
            and_(InquiryMessage.created_at == cursor.created_at, InquiryMessage.id < cursor.id)))
    messages = (await db.scalars(stmt.order_by(InquiryMessage.created_at.desc(), InquiryMessage.id.desc()).limit(51))).all()
    return {"chat": await service.metadata(db, row, user), "messages": [service.message_view(message, user) for message in reversed(messages[:50])], "has_more": len(messages) > 50}


@router.post("/{identifier}/read")
async def read(identifier: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await service.own(db, identifier, user, lock=True)
    if row.buyer_id == user.id: row.buyer_read_at = datetime.utcnow()
    else: row.seller_read_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.post("/{identifier}/messages")
async def send(identifier: UUID, body: str = Form("", max_length=2000), photo: UploadFile | None = File(None), client_id: UUID | None = Form(None),
               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await service.lock_sender(db, user)
    row = await service.own(db, identifier, user, lock=True)
    if row.linked_deal_id:
        raise HTTPException(409, "Переписка перенесена в чат оплаченной сделки")
    if client_id:
        previous = await db.scalar(select(InquiryMessage).where(InquiryMessage.inquiry_id == row.id,
            InquiryMessage.sender_id == user.id, InquiryMessage.client_id == client_id))
        if previous: return service.message_view(previous, user)
    await service.rate_limit(db, user)
    counterpart = await db.get(User, row.seller_id if row.buyer_id == user.id else row.buyer_id)
    if not counterpart or counterpart.is_blocked: raise HTTPException(403, "Переписка недоступна")
    if not body.strip() and photo is None: raise HTTPException(400, "Введите сообщение или добавьте фото")
    filename = None
    if photo is not None:
        content = await photo.read(settings.DEAL_MEDIA_MAX_SIZE + 1)
        try: filename = await asyncio.to_thread(deal_media.save_photo, content, row.id)
        except deal_media.MediaError as exc: raise HTTPException(400, str(exc))
    count = await db.scalar(select(func.count()).select_from(InquiryMessage).where(InquiryMessage.inquiry_id == row.id))
    if not count and not row.paid_order_id: row.expires_at = datetime.utcnow() + service.TTL
    message = InquiryMessage(inquiry_id=row.id, sender_id=user.id, text=body.strip() or None, photo_path=filename, client_id=client_id)
    db.add(message)
    await db.commit()
    for party in (row.buyer_id, row.seller_id):
        await manager.send_personal_message({"type":"inquiry_message", "chat_id":str(row.id)}, str(party))
    return service.message_view(message, user)
