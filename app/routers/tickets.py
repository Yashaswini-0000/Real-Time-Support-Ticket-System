import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.dependencies import get_current_user, require_roles
from app.database import get_db
from app.models import (
    Ticket,
    User,
    Category,
    Agent,
    AgentCategory,
    SLAPolicy,
    StatusHistory,
)
from app.routers.notifications import create_notification
router = APIRouter(prefix="/tickets", tags=["Tickets"])
PRIORITIES = {"Low", "Medium", "High", "Urgent"}
STATUSES = {"Open", "In Progress", "Pending", "Resolved", "Closed"}
OPEN_STATUSES = {"Open", "In Progress", "Pending"}
class TicketCreate(BaseModel):
    category_id: int = Field(gt=0)
    subject: str = Field(min_length=5, max_length=150)
    description: str = Field(min_length=10)
    priority: str = "Medium"
class TicketUpdate(BaseModel):
    subject: str | None = Field(default=None, min_length=5, max_length=150)
    description: str | None = Field(default=None, min_length=10)
    category_id: int | None = Field(default=None, gt=0)
class PriorityUpdate(BaseModel):
    priority: str
class TicketStatusUpdate(BaseModel):
    status: str
def ticket_response(ticket: Ticket):
    return {
     "id": ticket.id,
     "ticket_number": ticket.ticket_number,
     "customer_id": ticket.customer_id,
     "category_id": ticket.category_id,
     "assigned_agent_id": ticket.assigned_agent_id,
     "subject": ticket.subject,
     "description": ticket.description,
     "priority": ticket.priority,
     "status": ticket.status,
     "first_response_due": ticket.first_response_due,
     "resolution_due": ticket.resolution_due,
     "reopen_count": ticket.reopen_count,
     "sla_breached": ticket.sla_breached,
    }
async def can_access_ticket(ticket: Ticket, user: User, db: AsyncSession):
    role = user.role.upper()
    if role == "ADMIN":
     return True
    if role == "CUSTOMER" and ticket.customer_id == user.id:
     return True
    if role == "AGENT":
     result = await db.execute(
         select(Agent).where(Agent.user_id == user.id)
     )
     agent = result.scalar_one_or_none()
     return bool(agent and ticket.assigned_agent_id == agent.id)
    return False
async def get_ticket_or_404(ticket_id: int, db: AsyncSession):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
     raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket
async def set_sla_deadlines(ticket: Ticket, db: AsyncSession):
    result = await db.execute(
     select(SLAPolicy).where(SLAPolicy.priority == ticket.priority)
    )
    policy = result.scalar_one_or_none()
    if not policy:
     raise HTTPException(
         status_code=400,
         detail=f"No SLA policy configured for priority {ticket.priority}",
     )
    now = datetime.utcnow()
    if not ticket.first_response_at:
     ticket.first_response_due = now + timedelta(
         minutes=policy.first_response_minutes
     )
    if not ticket.resolved_at:
     ticket.resolution_due = now + timedelta(
         minutes=policy.resolution_minutes
     )
async def notify_ticket_owner(ticket: Ticket, title: str, message: str):
    await create_notification(
     user_id=ticket.customer_id,
     title=title,
     message=message,
     ticket_id=ticket.id,
    )
@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_ticket(
    data: TicketCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role.upper() != "CUSTOMER":
     raise HTTPException(403, "Only customers can create tickets")
    if data.priority not in PRIORITIES:
     raise HTTPException(400, "Invalid priority")
    category = await db.get(Category, data.category_id)
    if not category:
     raise HTTPException(404, "Category not found")
    if not category.is_active:
     raise HTTPException(400, "Category is inactive")
    ticket = Ticket(
     ticket_number=f"TKT-{uuid.uuid4().hex[:8].upper()}",
     customer_id=user.id,
     category_id=data.category_id,
     subject=data.subject,
     description=data.description,
     priority=data.priority,
     status="Open",
    )
    await set_sla_deadlines(ticket, db)
    db.add(ticket)
    await db.flush()
    db.add(
     StatusHistory(
         ticket_id=ticket.id,
         old_status=None,
         new_status="Open",
         changed_by=user.id,
     )
    )
    await db.commit()
    await db.refresh(ticket)
    await notify_ticket_owner(
     ticket,
     "Ticket created",
     f"Your ticket {ticket.ticket_number} has been created.",
    )
    return ticket_response(ticket)
@router.get("/")
async def list_tickets(
    skip: int = Query(default=0, ge=0, description="Number of tickets to skip"),
    limit: int = Query(default=10, ge=1, le=100, description="Maximum tickets to return"),
    search: str | None = Query(default=None, min_length=1, max_length=150),
    ticket_status: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    category_id: int | None = Query(default=None, gt=0),
    sort_by: str = Query(default="id", description="id, created_at, subject, status, priority, ticket_number"),
    order: str = Query(default="desc", description="asc or desc"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List tickets with role-based access, pagination, search, filtering and sorting."""
    query = select(Ticket)

    # Preserve role-based access: customers see their own tickets, agents see assigned tickets.
    if user.role.upper() == "CUSTOMER":
        query = query.where(Ticket.customer_id == user.id)
    elif user.role.upper() == "AGENT":
        result = await db.execute(select(Agent).where(Agent.user_id == user.id))
        agent = result.scalar_one_or_none()
        if not agent:
            return []
        query = query.where(Ticket.assigned_agent_id == agent.id)
    elif user.role.upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Search ticket number, subject and description.
    if search:
        search_term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Ticket.ticket_number.ilike(search_term),
                Ticket.subject.ilike(search_term),
                Ticket.description.ilike(search_term),
            )
        )

    # Optional filters.
    if ticket_status is not None:
        if ticket_status not in STATUSES:
            raise HTTPException(status_code=400, detail="Invalid ticket status filter")
        query = query.where(Ticket.status == ticket_status)

    if priority is not None:
        if priority not in PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority filter")
        query = query.where(Ticket.priority == priority)

    if category_id is not None:
        query = query.where(Ticket.category_id == category_id)

    # Whitelist sortable columns to prevent invalid sort fields.
    sort_columns = {
        "id": Ticket.id,
        "created_at": Ticket.created_at,
        "subject": Ticket.subject,
        "status": Ticket.status,
        "priority": Ticket.priority,
        "ticket_number": Ticket.ticket_number,
    }
    if sort_by not in sort_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_by. Choose one of: {', '.join(sort_columns.keys())}",
        )

    normalized_order = order.lower()
    if normalized_order not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="order must be 'asc' or 'desc'")

    sort_column = sort_columns[sort_by]
    query = query.order_by(asc(sort_column) if normalized_order == "asc" else desc(sort_column))
    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    return [ticket_response(ticket) for ticket in result.scalars().all()]
@router.get("/open-counts")
async def get_open_ticket_counts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "AGENT")),
):
    """Return open-ticket counts for the current admin or agent."""
    query = select(Ticket.status, func.count(Ticket.id)).where(
        Ticket.status.in_(OPEN_STATUSES)
    )
    if user.role.upper() == "AGENT":
        result = await db.execute(
            select(Agent).where(Agent.user_id == user.id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent profile not found")
        query = query.where(Ticket.assigned_agent_id == agent.id)
    query = query.group_by(Ticket.status)
    result = await db.execute(query)
    counts = {status_name: count for status_name, count in result.all()}
    total = sum(counts.values())
    return {
        "user_id": user.id,
        "role": user.role.upper(),
        "total_open_tickets": total,
        "by_status": {
            "Open": counts.get("Open", 0),
            "In Progress": counts.get("In Progress", 0),
            "Pending": counts.get("Pending", 0),
        },
    }
@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = await get_ticket_or_404(ticket_id, db)
    if not await can_access_ticket(ticket, user, db):
     raise HTTPException(403, "You cannot access this ticket")
    return ticket_response(ticket)
@router.put("/{ticket_id}")
async def update_ticket(
    ticket_id: int,
    data: TicketUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = await get_ticket_or_404(ticket_id, db)
    if not await can_access_ticket(ticket, user, db):
     raise HTTPException(403, "You cannot access this ticket")
    if ticket.status == "Closed":
     raise HTTPException(400, "Closed tickets cannot be updated")
    if user.role.upper() == "AGENT":
     raise HTTPException(403, "Agents cannot edit ticket details")
    updates = data.model_dump(exclude_unset=True)
    if "category_id" in updates:
     category = await db.get(Category, updates["category_id"])
     if not category:
         raise HTTPException(404, "Category not found")
     if not category.is_active:
         raise HTTPException(400, "Category is inactive")
    for field, value in updates.items():
     setattr(ticket, field, value)
    await db.commit()
    await db.refresh(ticket)
    return ticket_response(ticket)
@router.put("/{ticket_id}/priority")
async def update_ticket_priority(
    ticket_id: int,
    data: PriorityUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "AGENT")),
):
    ticket = await get_ticket_or_404(ticket_id, db)
    if ticket.status == "Closed":
     raise HTTPException(400, "Closed tickets cannot be updated")
    if data.priority not in PRIORITIES:
     raise HTTPException(400, "Invalid priority")
    if user.role.upper() == "AGENT":
     result = await db.execute(
         select(Agent).where(Agent.user_id == user.id)
     )
     agent = result.scalar_one_or_none()
     if not agent or ticket.assigned_agent_id != agent.id:
         raise HTTPException(403, "Ticket is not assigned to you")
    ticket.priority = data.priority
    await set_sla_deadlines(ticket, db)
    await db.commit()
    await db.refresh(ticket)
    return ticket_response(ticket)
@router.put("/{ticket_id}/status")
@router.patch("/{ticket_id}/status")
async def update_ticket_status(
    ticket_id: int,
    data: TicketStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "AGENT")),
):
    ticket = await get_ticket_or_404(ticket_id, db)
    if ticket.status == "Closed":
     raise HTTPException(400, "Closed tickets cannot be updated")
    if data.status not in STATUSES:
     raise HTTPException(400, "Invalid ticket status")
    if user.role.upper() == "AGENT":
     result = await db.execute(
         select(Agent).where(Agent.user_id == user.id)
     )
     agent = result.scalar_one_or_none()
     if not agent or ticket.assigned_agent_id != agent.id:
         raise HTTPException(403, "Ticket is not assigned to you")
    old_status = ticket.status
    ticket.status = data.status
    if data.status == "Resolved":
     ticket.resolved_at = datetime.utcnow()
    elif data.status == "Closed":
     ticket.closed_at = datetime.utcnow()
    db.add(
     StatusHistory(
         ticket_id=ticket.id,
         old_status=old_status,
         new_status=data.status,
         changed_by=user.id,
     )
    )
    await db.commit()
    await db.refresh(ticket)
    await notify_ticket_owner(
     ticket,
     "Ticket status updated",
     f"Ticket {ticket.ticket_number} status changed from "
     f"{old_status} to {ticket.status}.",
    )
    return ticket_response(ticket)
@router.put("/{ticket_id}/reopen")
async def reopen_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = await get_ticket_or_404(ticket_id, db)
    if ticket.customer_id != user.id and user.role.upper() != "ADMIN":
     raise HTTPException(
         403, "Only the ticket owner or admin can reopen"
     )
    if ticket.status not in {"Resolved", "Closed"}:
     raise HTTPException(
         400, "Only resolved or closed tickets can be reopened"
     )
    now = datetime.utcnow()
    closed_time = ticket.closed_at or ticket.resolved_at
    if not closed_time or now - closed_time > timedelta(days=7):
     raise HTTPException(
         400, "Tickets can only be reopened within 7 days"
     )
    if ticket.reopen_count >= 2:
     raise HTTPException(400, "Maximum reopen limit reached")
    old_status = ticket.status
    ticket.status = "Open"
    ticket.reopen_count += 1
    ticket.resolved_at = None
    ticket.closed_at = None
    await set_sla_deadlines(ticket, db)
    db.add(
     StatusHistory(
         ticket_id=ticket.id,
         old_status=old_status,
         new_status="Open",
         changed_by=user.id,
     )
    )
    await db.commit()
    await db.refresh(ticket)
    await notify_ticket_owner(
     ticket,
     "Ticket reopened",
     f"Ticket {ticket.ticket_number} has been reopened.",
    )
    return ticket_response(ticket)
@router.get("/{ticket_id}/history")
async def get_ticket_history(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ticket = await get_ticket_or_404(ticket_id, db)
    if not await can_access_ticket(ticket, user, db):
     raise HTTPException(403, "You cannot access this ticket")
    result = await db.execute(
     select(StatusHistory)
     .where(StatusHistory.ticket_id == ticket_id)
     .order_by(StatusHistory.changed_at.asc())
    )
    return [
     {
         "id": item.id,
         "ticket_id": item.ticket_id,
         "old_status": item.old_status,
         "new_status": item.new_status,
         "changed_by": item.changed_by,
         "changed_at": item.changed_at,
     }
     for item in result.scalars().all()
    ]
@router.put("/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    ticket = await get_ticket_or_404(ticket_id, db)
    if ticket.status == "Closed":
     raise HTTPException(400, "Closed tickets cannot be assigned")
    result = await db.execute(
     select(Agent)
     .join(AgentCategory, AgentCategory.agent_id == Agent.id)
     .where(
         AgentCategory.category_id == ticket.category_id,
         Agent.availability == "Online",
         Agent.is_active.is_(True),
     )
    )
    eligible_agents = result.scalars().unique().all()
    candidates = []
    for agent in eligible_agents:
     count_result = await db.execute(
         select(func.count(Ticket.id)).where(
             Ticket.assigned_agent_id == agent.id,
             Ticket.status.in_(OPEN_STATUSES),
         )
     )
     open_count = count_result.scalar_one()
     if open_count < agent.max_open_tickets:
         candidates.append((open_count, agent.id, agent))
    if not candidates:
     raise HTTPException(
         404,
         "No eligible online agent is available for this category",
     )
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, _, selected_agent = candidates[0]
    previous_agent_id = ticket.assigned_agent_id
    ticket.assigned_agent_id = selected_agent.id
    db.add(
     StatusHistory(
         ticket_id=ticket.id,
         old_status=ticket.status,
         new_status=ticket.status,
         changed_by=user.id,
     )
    )
    await db.commit()
    await db.refresh(ticket)
    await create_notification(
     user_id=selected_agent.user_id,
     title="Ticket assigned",
     message=f"Ticket {ticket.ticket_number} has been assigned to you.",
     ticket_id=ticket.id,
    )
    await notify_ticket_owner(
     ticket,
     "Agent assigned",
     f"An agent has been assigned to ticket {ticket.ticket_number}.",
    )
    return {
     "message": "Ticket assigned successfully",
     "ticket_id": ticket.id,
     "previous_agent_id": previous_agent_id,
     "assigned_agent_id": selected_agent.id,
     "assigned_agent_name": selected_agent.name,
    }
@router.get("/agents/me/tickets")
async def get_my_assigned_tickets(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles("AGENT")),
):
    result = await db.execute(
     select(Agent).where(Agent.user_id == user.id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
     raise HTTPException(404, "Agent profile not found")
    result = await db.execute(
     select(Ticket)
     .where(Ticket.assigned_agent_id == agent.id)
     .order_by(Ticket.id.desc())
     .offset(skip)
     .limit(limit)
    )
    return [ticket_response(ticket) for ticket in result.scalars().all()]
