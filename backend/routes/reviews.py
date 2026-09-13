from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from database import get_db
from models.user import User
from models.review import Review
from models.order import Order, OrderStatus
from models.product import Product
from schemas.review import ReviewCreate, ReviewResponse, FakeReviewCreate
from utils.auth import get_current_user, require_admin
from services.telegram_service import telegram_service

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


from sqlalchemy.orm import joinedload

@router.get("", response_model=list[ReviewResponse])
async def get_reviews(
    product_id: str = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """Get reviews for a product with pagination"""
    stmt = select(Review).where(Review.is_hidden == False).options(joinedload(Review.user), joinedload(Review.product))
    
    if product_id:
        stmt = stmt.where(Review.product_id == uuid.UUID(product_id))
    
    stmt = stmt.order_by(Review.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    reviews = result.scalars().all()
    
    return [ReviewResponse.model_validate(review) for review in reviews]


@router.post("", response_model=ReviewResponse)
async def create_review(
    review_data: ReviewCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create review for purchased product"""
    # Verify order belongs to user and is completed
    from sqlalchemy.orm import selectinload
    stmt = select(Order).options(selectinload(Order.items)).where(Order.id == review_data.order_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order or order.user_id != user.id:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.status != OrderStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Can only review completed orders")
    
    # Verify product is in the order
    order_has_product = any(item.product_id == review_data.product_id for item in order.items)
    if not order_has_product:
        raise HTTPException(status_code=400, detail="Product not in this order")
    
    # Check if review already exists
    stmt = select(Review).where(
        Review.user_id == user.id,
        Review.product_id == review_data.product_id,
        Review.order_id == review_data.order_id
    )
    result = await db.execute(stmt)
    existing_review = result.scalar_one_or_none()
    
    if existing_review:
        raise HTTPException(status_code=400, detail="Review already exists for this product")
    
    # Get product
    product = await db.get(Product, review_data.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Create review and sanitize text (strip tags)
    import re
    sanitized_text = re.sub('<[^<]+?>', '', review_data.text)
    
    review = Review(
        id=uuid.uuid4(),
        user_id=user.id,
        product_id=review_data.product_id,
        order_id=review_data.order_id,
        text=sanitized_text,
        rating=review_data.rating
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    
    # Manually attach user to avoid lazy load issue after commit
    review.user = user
    
    # Publish to Telegram channel
    try:
        message_id = await telegram_service.publish_review_to_channel(
            product_name=product.name_ru,
            price_usdt=float(product.price_usdt),
            review_text=review_data.text,
            rating=review_data.rating,
            product_id=str(product.id)
        )
        
        review.telegram_message_id = message_id
        await db.commit()
    except Exception as e:
        # Don't fail if Telegram posting fails
        print(f"Failed to post review to Telegram: {e}")
    
    return ReviewResponse.model_validate(review)


@router.post("/admin/fake", response_model=ReviewResponse)
async def create_fake_review(
    review_data: FakeReviewCreate,
    admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Create a fake review (admin only). Publishes to Telegram channels like a real review."""
    import re

    # Verify product exists
    product = await db.get(Product, review_data.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    sanitized_text = re.sub('<[^<]+?>', '', review_data.text)

    review = Review(
        id=uuid.uuid4(),
        user_id=None,
        order_id=None,
        product_id=review_data.product_id,
        text=sanitized_text,
        rating=review_data.rating,
        is_fake=True,
        fake_username=review_data.fake_username,
        fake_quantity=review_data.fake_quantity,
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)

    # Load product relationship
    review.product = product

    # Publish to Telegram channels (same as real reviews)
    try:
        message_id = await telegram_service.publish_review_to_channel(
            product_name=product.name_ru,
            price_usdt=float(product.price_usdt),
            review_text=review_data.text,
            rating=review_data.rating,
            product_id=str(product.id),
            username=review_data.fake_username,
            quantity=review_data.fake_quantity,
        )

        review.telegram_message_id = message_id
        await db.commit()
    except Exception as e:
        print(f"Failed to post fake review to Telegram: {e}")

    return ReviewResponse.model_validate(review)


@router.delete("/{review_id}")
async def delete_review(
    review_id: str,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Delete review (admin only)"""
    review = await db.get(Review, uuid.UUID(review_id))
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    await db.delete(review)
    await db.commit()

    return {"message": "Review deleted"}


@router.put("/{review_id}/hide")
async def hide_review(
    review_id: str,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Hide review (admin only)"""
    review = await db.get(Review, uuid.UUID(review_id))
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    
    review.is_hidden = True
    await db.commit()
    
    return {"message": "Review hidden"}


@router.put("/{review_id}/unhide")
async def unhide_review(
    review_id: str,
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Unhide review (admin only)"""
    review = await db.get(Review, uuid.UUID(review_id))
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    
    review.is_hidden = False
    await db.commit()
    
    return {"message": "Review unhidden"}


@router.get("/admin/all", response_model=list[ReviewResponse])
async def get_all_reviews(
    admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get all reviews including hidden (admin only)"""
    stmt = select(Review).options(joinedload(Review.user), joinedload(Review.product)).order_by(Review.created_at.desc())
    result = await db.execute(stmt)
    reviews = result.scalars().all()
    
    return [ReviewResponse.model_validate(review) for review in reviews]
