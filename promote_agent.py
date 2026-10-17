
import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.id == 3)
        )
        user = result.scalar_one_or_none()

        if not user:
            print("User ID 3 not found.")
            return

        user.role = "AGENT"
        user.is_active = True

        await db.commit()

        print("User promoted to AGENT successfully.")
        print(f"User ID: {user.id}")
        print(f"Username: {user.username}")
        print(f"Role: {user.role}")


if __name__ == "__main__":
    asyncio.run(main())
