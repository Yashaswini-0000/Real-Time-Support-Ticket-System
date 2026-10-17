
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Ticket, Notification, User, Agent, StatusHistory


scheduler = AsyncIOScheduler()


async def check_sla_deadlines():
    """Detect SLA breaches, escalate priority, and notify users."""
    now = datetime.utcnow()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Ticket).where(
                Ticket.status.notin_(["Resolved", "Closed"]),
                Ticket.sla_breached.is_(False),
            )
        )
        tickets = result.scalars().all()

        admin_result = await db.execute(
            select(User).where(
                User.role == "ADMIN",
                User.is_active.is_(True),
            )
        )
        admins = admin_result.scalars().all()

        priority_levels = ["Low", "Medium", "High", "Urgent"]

        for ticket in tickets:
            reasons = []

            # Check first-response SLA.
            if (
                ticket.first_response_at is None
                and ticket.first_response_due is not None
                and ticket.first_response_due <= now
            ):
                reasons.append("first response SLA")

            # Pause resolution-SLA checking while waiting for the customer.
            if (
                ticket.status != "Waiting on Customer"
                and ticket.resolved_at is None
                and ticket.resolution_due is not None
                and ticket.resolution_due <= now
            ):
                reasons.append("resolution SLA")

            if not reasons:
                continue

            # Mark this breach so the same breach is not escalated again.
            ticket.sla_breached = True

            old_priority = ticket.priority
            current_index = (
                priority_levels.index(old_priority)
                if old_priority in priority_levels
                else 1
            )

            # Escalate one level. Urgent tickets remain Urgent.
            if current_index < len(priority_levels) - 1:
                ticket.priority = priority_levels[current_index + 1]

            reason_text = " and ".join(reasons)
            message = (
                f"Ticket {ticket.ticket_number} exceeded its "
                f"{reason_text}. Priority: {old_priority} -> "
                f"{ticket.priority}. Please review and take action."
            )

            # Notify the assigned agent.
            if ticket.assigned_agent_id is not None:
                agent = await db.get(Agent, ticket.assigned_agent_id)

                if agent is not None:
                    db.add(
                        Notification(
                            user_id=agent.user_id,
                            ticket_id=ticket.id,
                            title="SLA Breach Alert",
                            message=message,
                            is_read=False,
                        )
                    )

            # Notify administrators, including for Urgent tickets.
            for admin in admins:
                db.add(
                    Notification(
                        user_id=admin.id,
                        ticket_id=ticket.id,
                        title="SLA Breach Escalation",
                        message=message,
                        is_read=False,
                    )
                )

            # Record the priority change in ticket history.
            db.add(
                StatusHistory(
                    ticket_id=ticket.id,
                    old_status=f"Priority: {old_priority}",
                    new_status=f"Priority: {ticket.priority}",
                    changed_by=None,
                    changed_at=now,
                )
            )

        await db.commit()


async def auto_close_resolved_tickets():
    """Close resolved tickets that have remained resolved for seven days."""
    now = datetime.utcnow()
    cutoff = now - timedelta(days=7)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Ticket).where(
                Ticket.status == "Resolved",
                Ticket.resolved_at.is_not(None),
                Ticket.resolved_at <= cutoff,
            )
        )
        tickets = result.scalars().all()

        for ticket in tickets:
            old_status = ticket.status
            ticket.status = "Closed"
            ticket.closed_at = now

            db.add(
                StatusHistory(
                    ticket_id=ticket.id,
                    old_status=old_status,
                    new_status="Closed",
                    changed_by=None,
                    changed_at=now,
                )
            )

        await db.commit()


def start_sla_scheduler():
    """Start background jobs when the application starts."""
    if scheduler.running:
        return

    scheduler.add_job(
        check_sla_deadlines,
        trigger="interval",
        minutes=5,
        id="sla_deadline_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        auto_close_resolved_tickets,
        trigger="interval",
        days=1,
        id="auto_close_resolved_tickets",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()


def stop_sla_scheduler():
    """Stop the scheduler safely."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
