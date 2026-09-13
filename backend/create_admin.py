import asyncio
import uuid
from database import AsyncSessionLocal
from models.user import User
from config import settings

async def create_admin():
    async with AsyncSessionLocal() as db:
        print("Creating admin user...")
        # Check if exists
        # For simplicity, just create a new one with a fixed ID or similar
        
        # User auth in this app seems to match Telegram ID?
        # Let's check User model.
        # User model has telegram_id (BigInt).
        
        # We'll create a dev admin with telegram_id=123456789 (common mock)
        # or just rely on 'Login as Developer' to create it.
        # Let's make sure 'Login as Developer' works.
        
        # But if the user needs access to Admin Panel, they need 'is_admin=True'.
        # I will create a user with telegram_id=12345 (dev) and is_admin=True.
        
        dev_user = User(
            id=uuid.uuid4(),
            telegram_id=12345,
            username="dev_admin",
            first_name="Dev Admin",
            language_code="en",
            is_admin=True,
            referral_code="admin"
        )
        
        try:
            db.add(dev_user)
            await db.commit()
            print("Admin created. ID: 12345")
        except Exception as e:
            print(f"Error creating admin (probably exists): {e}")

if __name__ == "__main__":
    asyncio.run(create_admin())
