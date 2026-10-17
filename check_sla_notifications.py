
import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Notification


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Notification)
            .where(
                Notification.ticket_id == 2,
                Notification.title.in_([
                    "SLA Breach Escalation",
                    "SLA Breach Alert",
                ]),
            )
            .order_by(Notification.id.desc())
        )

        notifications = result.scalars().all()

        if not notifications:
            print("No SLA notifications found for ticket 2.")
        else:
            for n in notifications:
                print(
                    f"ID={n.id} | User={n.user_id} | "
                    f"Ticket={n.ticket_id} | Title={n.title}"
                )
                print(f"Message: {n.message}\n")


if __name__ == "__main__":
    asyncio.run(main())
