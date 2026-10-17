
import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User
from app.auth.security import hash_password


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.username == "support_admin"
            )
        )
        user = result.scalar_one_or_none()

        if user:
            user.role = "ADMIN"
            user.is_active = True
            print("Existing user updated to ADMIN.")
        else:
            user = User(
                username="support_admin",
                email="support_admin@example.com",
                hashed_password=hash_password(
                    "ChangeThisAdminPass123!"
                ),
                role="ADMIN",
                is_active=True,
            )
            db.add(user)
            print("Admin user created.")

        await db.commit()
        print("Username: support_admin")
        print("Email: support_admin@example.com")
        print("Password: ChangeThisAdminPass123!")


if __name__ == "__main__":
    asyncio.run(main())
