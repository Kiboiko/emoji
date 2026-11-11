from datetime import datetime, timezone
import re
import httpx
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from config import settings
from database import get_db
from models.giveaway import Giveaway, GiveawayChat, GiveawayEntry, GiveawayDrawAttempt, GiveawayPostCleanup
from models.user import User
from services import giveaway_service as service, audit_service, image_upload, image_variants
from services.market_ranking_service import iso
from services import giveaway_lifecycle as lifecycle
from services import nft_preview
from utils.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/giveaways", tags=["Giveaways"])
admin_router = APIRouter(prefix="/api/admin/giveaways", tags=["Admin giveaways"])


async def view(db, row, admin=False):
    requirements = await service.chats(db, row.id)
    count = await db.scalar(select(func.count()).select_from(GiveawayEntry).where(
        GiveawayEntry.giveaway_id == row.id, GiveawayEntry.status.in_(("joined", "winner"))))
    result = {"id": str(row.id), "title_ru": row.title_ru, "title_en": row.title_en,
        "description_ru": row.description_ru, "description_en": row.description_en, "prize": row.prize,
        "photo_url": row.photo_url, "start_at": iso(row.start_at), "end_at": iso(row.end_at), "status": row.status,
        "participants": count, "winner": row.public_winner_label, "winner_username": row.public_winner_username,
        "fulfillment_status": row.fulfillment_status, "requirements": [
            {"id": str(c.id), "title": c.title, "join_link": c.join_link} for c in requirements]}
    if admin:
        result.update(version=row.version, winner_user_id=str(row.winner_user_id) if row.winner_user_id else None,
            post_chat_id=str(row.post_chat_id) if row.post_chat_id else None, post_status=row.post_status,
            post_message_id=row.post_message_id,
            snapshot_count=row.snapshot_count, snapshot_hash=row.snapshot_hash, error_code=row.error_code,
            draw_started_at=iso(row.draw_started_at), finished_at=iso(row.finished_at),
            requirements=[{"chat_id": str(c.chat_id), "title": c.title, "join_link": c.join_link} for c in requirements])
    return result


@router.get("")
async def listing(skip: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Giveaway).where(Giveaway.status != "draft", lifecycle.retained_condition())
        .order_by((Giveaway.status == "finished").asc(), Giveaway.created_at.desc(), Giveaway.id).offset(skip).limit(20))).all()
    return [await view(db, row) for row in rows]


@router.get("/{giveaway_id}")
async def detail(giveaway_id: UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(Giveaway, giveaway_id)
    if row is None or row.status == "draft" or lifecycle.expired(row):
        raise HTTPException(404, "Розыгрыш не найден")
    return await view(db, row)


@router.get("/{giveaway_id}/my-entry")
async def my_entry(giveaway_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await db.get(Giveaway, giveaway_id)
    if not row or row.status == "draft" or lifecycle.expired(row):
        raise HTTPException(404, "Розыгрыш не найден")
    entry = await db.scalar(select(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway_id, GiveawayEntry.user_id == user.id))
    joined = bool(entry and entry.status in ("joined", "winner"))
    return {"joined": joined, "status": entry.status if entry else None,
        "entry_label": "Участник " + entry.id.hex[:8] if joined else None, "is_winner": row.winner_user_id == user.id}


@router.post("/{giveaway_id}/join")
async def join(giveaway_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        return await service.verify_entry(db, giveaway_id, user, join=True)
    except service.GiveawayError as exc:
        raise HTTPException(409, str(exc))


@router.post("/{giveaway_id}/check-membership")
async def check_membership(giveaway_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        return await service.verify_entry(db, giveaway_id, user)
    except service.GiveawayError as exc:
        raise HTTPException(409, str(exc))


class RequiredChat(BaseModel):
    chat_id: int = Field(lt=0, ge=-9_000_000_000_000_000)
    title: str = Field(min_length=1, max_length=200)
    join_link: str = Field(max_length=500)

    @field_validator("join_link")
    @classmethod
    def telegram_link(cls, value):
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.netloc != "t.me" or not parsed.path.strip("/"):
            raise ValueError("Нужна ссылка https://t.me/...")
        return value


class GiveawayIn(BaseModel):
    title_ru: str = Field("Giveaway", min_length=1, max_length=200)
    title_en: str = Field("Giveaway", min_length=1, max_length=200)
    description_ru: str = Field("", max_length=10000)
    description_en: str = Field("", max_length=10000)
    prize: str = Field(min_length=1, max_length=500)
    nft_link: str | None = Field(None, max_length=500)
    photo_url: str | None = Field(None, max_length=500)
    post_chat_id: int | None = Field(None, lt=0, ge=-9_000_000_000_000_000)
    start_at: datetime
    end_at: datetime
    requirements: list[RequiredChat] = Field(min_length=1, max_length=10)

    @field_validator("start_at", "end_at")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None:
            raise ValueError("Укажите время с часовым поясом")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @field_validator("photo_url")
    @classmethod
    def local_photo(cls, value):
        if value and (not value.startswith("/uploads/") or ".." in value):
            raise ValueError("Используйте загруженное фото")
        return value

    @model_validator(mode="after")
    def valid(self):
        if self.nft_link:
            self.prize = nft_preview.gift_url(self.nft_link)
        if self.end_at <= self.start_at or len({c.chat_id for c in self.requirements}) != len(self.requirements):
            raise ValueError("Неверный срок или повторяющиеся чаты")
        return self


@admin_router.get("")
async def administration(skip: int = Query(0, ge=0), admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Giveaway).where(lifecycle.retained_condition()).order_by(Giveaway.created_at.desc()).offset(skip).limit(30))).all()
    return [await view(db, row, admin=True) for row in rows]


@admin_router.get("/cleanup-status")
async def cleanup_status(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count()).select_from(GiveawayPostCleanup))
    retrying = await db.scalar(select(func.count()).select_from(GiveawayPostCleanup).where(GiveawayPostCleanup.attempts > 0))
    return {"pending": total, "retrying": retrying}


@admin_router.get("/post-channels")
async def post_channels(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    from models.subscription import Channel
    rows = (await db.scalars(select(Channel).order_by(Channel.title).limit(200))).all()
    return [{"chat_id": str(row.telegram_chat_id), "title": row.display_title(), "username": row.username} for row in rows]


class PostChannelIn(BaseModel):
    channel: str = Field(min_length=2, max_length=80)


@admin_router.post("/resolve-post-channel")
async def resolve_post_channel(body: PostChannelIn, admin: User = Depends(require_admin)):
    from services.telegram_service import _call, TelegramApiError
    channel = body.channel.strip()
    if not re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,31}|-[0-9]{1,16}", channel):
        raise HTTPException(422, "Укажите @username или отрицательный ID канала")
    try:
        chat = await _call("getChat", {"chat_id": int(channel) if channel.startswith('-') else channel})
        if chat.get("type") != "channel" or not isinstance(chat.get("id"), int) or chat["id"] >= 0:
            raise ValueError("Выберите канал для публикации")
        await lifecycle.check_post_target(chat["id"])
    except (TelegramApiError, ValueError):
        raise HTTPException(400, "Канал недоступен. Добавьте бота администратором с правом публикации.")
    except httpx.HTTPError:
        raise HTTPException(503, "Telegram временно недоступен. Повторите проверку канала.")
    return {"chat_id": str(chat["id"]), "title": chat.get("title", channel), "username": chat.get("username")}


async def save_draft(db, row, body):
    photo_url = await ensure_nft_photo(body.prize, body.photo_url)
    for key, value in body.model_dump(exclude={"requirements", "nft_link"}).items():
        setattr(row, key, value)
    row.photo_url = photo_url
    await db.flush()
    await db.execute(delete(GiveawayChat).where(GiveawayChat.giveaway_id == row.id))
    db.add_all([GiveawayChat(giveaway_id=row.id, **c.model_dump()) for c in body.requirements])
    await db.flush()


@admin_router.post("")
async def create(body: GiveawayIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    body.photo_url = await ensure_nft_photo(body.prize, body.photo_url)
    row = Giveaway(**body.model_dump(exclude={"requirements", "nft_link"}))
    db.add(row)
    await save_draft(db, row, body)
    audit_service.log_action(db, admin, "giveaway.create", target_type="giveaway", target_id=row.id)
    await db.commit()
    return await view(db, row, admin=True)


@admin_router.put("/{giveaway_id}")
async def edit(giveaway_id: UUID, body: GiveawayIn, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update())
    if row is None or row.status != "draft":
        raise HTTPException(409, "Изменять можно только черновик")
    row.version += 1
    await save_draft(db, row, body)
    audit_service.log_action(db, admin, "giveaway.edit", target_type="giveaway", target_id=row.id)
    await db.commit()
    return await view(db, row, admin=True)


@admin_router.post("/{giveaway_id}/publish")
async def publish(giveaway_id: UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    row = await db.get(Giveaway, giveaway_id)
    if row is None or row.status != "draft" or row.end_at <= datetime.utcnow():
        raise HTTPException(409, "Нужен действующий черновик")
    version = row.version
    photo_url = await ensure_nft_photo(row.prize, row.photo_url)
    requirements = await service.chats(db, row.id)
    await db.commit()
    try:
        if not requirements:
            raise ValueError()
        await service.preflight(requirements)
        if row.post_chat_id:
            lifecycle.participation_link(row.id)
            await lifecycle.check_post_target(row.post_chat_id)
    except Exception:
        raise HTTPException(400, "Бот должен быть администратором всех обязательных чатов; проверьте права и доступность Telegram")
    row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update().execution_options(populate_existing=True))
    if row is None or row.status != "draft" or row.version != version or row.end_at <= datetime.utcnow():
        raise HTTPException(409, "Черновик изменился, повторите проверку")
    row.status = "scheduled" if row.start_at > datetime.utcnow() else "open"
    row.photo_url = photo_url
    row.post_status = "queued" if row.post_chat_id else "disabled"
    audit_service.log_action(db, admin, "giveaway.publish", target_type="giveaway", target_id=row.id)
    await db.commit()
    return await view(db, row, admin=True)


@admin_router.post("/{giveaway_id}/cancel")
async def cancel(giveaway_id: UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update())
    if row is None or row.status in ("finished", "cancelled"):
        raise HTTPException(409, "Розыгрыш уже завершён")
    if row.post_status in ("sending", "unknown"):
        raise HTTPException(409, "Сначала уточните доставку поста и сохраните ID сообщения или подтвердите, что пост не отправлен")
    audit_service.log_action(db, admin, "giveaway.cancel", target_type="giveaway", target_id=row.id)
    await lifecycle.remove_record(db, row)
    await db.commit()
    return {"status": "deleted"}


@admin_router.post("/{giveaway_id}/fulfilled")
async def fulfilled(giveaway_id: UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update())
    if row is None or row.status != "finished" or not row.winner_user_id:
        raise HTTPException(409, "Сначала должен быть определён победитель")
    row.fulfillment_status = "delivered"
    audit_service.log_action(db, admin, "giveaway.fulfilled", target_type="giveaway", target_id=row.id)
    await db.commit()
    return {"fulfillment_status": row.fulfillment_status}


@admin_router.get("/{giveaway_id}/participants")
async def participants(giveaway_id: UUID, skip: int = Query(0, ge=0), admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(GiveawayEntry, User).join(User, User.id == GiveawayEntry.user_id)
        .where(GiveawayEntry.giveaway_id == giveaway_id).order_by(GiveawayEntry.id).offset(skip).limit(50))).all()
    return [{"entry_label": "Участник " + e.id.hex[:8], "status": e.status, "telegram_id": str(u.telegram_id),
        "name": u.first_name, "username": u.username, "error_code": e.error_code,
        "is_winner": e.status == "winner"} for e, u in rows]


@admin_router.post("/photo")
async def upload_photo(file: UploadFile = File(...), admin: User = Depends(require_admin)):
    content = await file.read(settings.MAX_UPLOAD_SIZE + 1)
    try:
        data, extension = await run_in_threadpool(image_upload.prepare, content, settings.MAX_UPLOAD_SIZE)
    except image_upload.ImageError as exc:
        raise HTTPException(400, str(exc))
    folder = Path(settings.UPLOAD_DIR) / "giveaways"
    folder.mkdir(parents=True, exist_ok=True)
    filename = uuid4().hex + extension
    (folder / filename).write_bytes(data)
    await run_in_threadpool(image_variants.build_quietly, Path(settings.UPLOAD_DIR), folder / filename)
    return {"url": "/uploads/giveaways/" + filename}


class NFTPreviewIn(BaseModel):
    url: str = Field(max_length=500)


@admin_router.post("/photo-from-nft")
async def photo_from_nft(body: NFTPreviewIn, admin: User = Depends(require_admin)):
    try:
        url, title = await nft_preview.save_preview(body.url.strip())
    except Exception:
        raise HTTPException(400, "Не удалось получить качественное фото NFT. Проверьте ссылку https://t.me/nft/... и повторите попытку.")
    return {"url": url, "title": title}


async def ensure_nft_photo(prize, photo_url):
    try:
        return await nft_preview.ensure_photo(prize, photo_url)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


class PostResolution(BaseModel):
    message_id: int | None = Field(None, gt=0)
    not_sent: bool = False

    @model_validator(mode="after")
    def one_outcome(self):
        if bool(self.message_id) == self.not_sent:
            raise ValueError("Укажите ID сообщения или подтвердите отсутствие поста")
        return self


@admin_router.post("/{giveaway_id}/post-resolution")
async def resolve_post(giveaway_id: UUID, body: PostResolution, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    from datetime import timedelta
    row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update())
    if not row or row.post_status not in ("unknown", "sending") or (row.post_status == "sending"
        and row.post_started_at and row.post_started_at > datetime.utcnow() - timedelta(minutes=2)):
        raise HTTPException(409, "Нет неизвестной доставки для уточнения")
    row.post_message_id, row.post_status = body.message_id, "sent" if body.message_id else "failed"
    audit_service.log_action(db, admin, "giveaway.post_resolution", target_type="giveaway", target_id=row.id)
    await db.commit()
    return {"post_status": row.post_status}


@admin_router.post("/{giveaway_id}/post-retry")
async def retry_post(giveaway_id: UUID, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id).with_for_update())
    if not row or row.post_status != "failed" or row.end_at <= datetime.utcnow() or not row.post_chat_id:
        raise HTTPException(409, "Нет поста для повтора")
    row.post_status = "queued"
    audit_service.log_action(db, admin, "giveaway.post_retry", target_type="giveaway", target_id=row.id)
    await db.commit()
    return {"post_status": row.post_status}


@admin_router.get("/{giveaway_id}/draw-attempts")
async def draw_attempts(giveaway_id: UUID, skip: int = Query(0, ge=0), admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(GiveawayDrawAttempt).where(GiveawayDrawAttempt.giveaway_id == giveaway_id)
        .order_by(GiveawayDrawAttempt.ordinal).offset(skip).limit(50))).all()
    return [{"ordinal": r.ordinal, "entry_label": "Участник " + r.entry_id.hex[:8],
        "status": r.status, "selected_at": iso(r.selected_at)} for r in rows]
