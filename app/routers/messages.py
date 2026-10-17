
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import Ticket, Message, User

router = APIRouter(
    prefix="/tickets/{ticket_id}/messages",
    tags=["Ticket Messages"],
)


class MessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


async def get_accessible_ticket(
    ticket_id: int,
    current_user: User,
    db: AsyncSession,
) -> Ticket:
    ticket = await db.get(Ticket, ticket_id)

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    role = current_user.role.upper()

    if role == "ADMIN":
        return ticket

    if role == "CUSTOMER" and ticket.customer_id == current_user.id:
        return ticket

    if role == "AGENT":
        from app.models import Agent

        if ticket.assigned_agent_id is not None:
            agent = await db.get(Agent, ticket.assigned_agent_id)
            if agent and agent.user_id == current_user.id:
                return ticket

    raise HTTPException(status_code=403, detail="Ticket access denied")


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_message(
    ticket_id: int,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await get_accessible_ticket(ticket_id, current_user, db)

    if ticket.status == "Closed":
        raise HTTPException(
            status_code=400,
            detail="Cannot send messages to a closed ticket",
        )

    message = Message(
        ticket_id=ticket_id,
        sender_id=current_user.id,
        sender_role=current_user.role.upper(),
        message=data.message.strip(),
        is_internal_note=False,
        is_read=False,
    )

    if not message.message:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    db.add(message)
    await db.commit()
    await db.refresh(message)

    return {
        "id": message.id,
        "ticket_id": message.ticket_id,
        "sender_id": message.sender_id,
        "sender_role": message.sender_role,
        "message": message.message,
        "is_internal_note": message.is_internal_note,
        "is_read": message.is_read,
        "created_at": message.created_at,
    }


@router.get("/")
async def list_messages(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_accessible_ticket(ticket_id, current_user, db)

    result = await db.execute(
        select(Message)
        .where(Message.ticket_id == ticket_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )

    messages = result.scalars().all()

    # Customers must not see internal notes.
    if current_user.role.upper() == "CUSTOMER":
        messages = [
            message for message in messages
            if not message.is_internal_note
        ]

    # Mark incoming messages as read when this user retrieves the conversation.
    changed = False
    for message in messages:
        if message.sender_id != current_user.id and not message.is_read:
            message.is_read = True
            changed = True

    if changed:
        await db.commit()

    return [
        {
            "id": message.id,
            "ticket_id": message.ticket_id,
            "sender_id": message.sender_id,
            "sender_role": message.sender_role,
            "message": message.message,
            "is_internal_note": message.is_internal_note,
            "is_read": message.is_read,
            "created_at": message.created_at,
        }
        for message in messages
    ]
