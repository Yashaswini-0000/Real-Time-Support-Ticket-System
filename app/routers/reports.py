
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.dependencies import require_roles
from app.models import Ticket, Agent, Category, Feedback, User

router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
)


@router.get("/overview")
async def get_report_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN")),
):
    total_tickets = await db.scalar(
        select(func.count(Ticket.id))
    )

    open_tickets = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.status.in_(["Open", "In Progress", "Pending"])
        )
    )

    resolved_tickets = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.status == "Resolved"
        )
    )

    closed_tickets = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.status == "Closed"
        )
    )

    breached_tickets = await db.scalar(
        select(func.count(Ticket.id)).where(
            Ticket.sla_breached.is_(True)
        )
    )

    return {
        "total_tickets": total_tickets or 0,
        "open_tickets": open_tickets or 0,
        "resolved_tickets": resolved_tickets or 0,
        "closed_tickets": closed_tickets or 0,
        "sla_breached_tickets": breached_tickets or 0,
    }


@router.get("/categories")
async def get_category_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN")),
):
    result = await db.execute(
        select(
            Category.id,
            Category.category_name,
            func.count(Ticket.id).label("ticket_count"),
        )
        .outerjoin(Ticket, Ticket.category_id == Category.id)
        .group_by(Category.id, Category.category_name)
        .order_by(Category.category_name)
    )

    return [
        {
            "category_id": row.id,
            "category_name": row.category_name,
            "ticket_count": row.ticket_count,
        }
        for row in result.all()
    ]


@router.get("/agents")
async def get_agent_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN")),
):
    result = await db.execute(
        select(
            Agent.id,
            Agent.name,
            Agent.availability,
            func.count(Ticket.id).label("assigned_tickets"),
        )
        .outerjoin(Ticket, Ticket.assigned_agent_id == Agent.id)
        .group_by(
            Agent.id,
            Agent.name,
            Agent.availability,
        )
        .order_by(Agent.name)
    )

    return [
        {
            "agent_id": row.id,
            "agent_name": row.name,
            "availability": row.availability,
            "assigned_tickets": row.assigned_tickets,
        }
        for row in result.all()
    ]


@router.get("/feedback")
async def get_feedback_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN")),
):
    average_rating = await db.scalar(
        select(func.avg(Feedback.rating))
    )

    total_feedback = await db.scalar(
        select(func.count(Feedback.id))
    )

    return {
        "total_feedback": total_feedback or 0,
        "average_rating": round(float(average_rating), 2)
        if average_rating is not None
        else None,
    }
