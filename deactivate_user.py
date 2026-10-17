import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.username == "support_agent2"
            )
        )
        user = result.scalar_one_or_none()

        if user:
            user.is_active = True
            await db.commit()
            print("User deactivated successfully.")
        else:
            print("User not found.")

if __name__ == "__main__":
    asyncio.run(main())