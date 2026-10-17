
import asyncio

from app.database import engine
from app.services.sla_monitor import (
    check_sla_deadlines,
    auto_close_resolved_tickets,
)


async def main():
    try:
        await check_sla_deadlines()
        print("SLA breach check completed.")

        await auto_close_resolved_tickets()
        print("Automatic ticket closure check completed.")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
