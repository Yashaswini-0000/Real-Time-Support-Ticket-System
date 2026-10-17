
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import Feedback, Ticket, User

router = APIRouter(prefix="/feedback", tags=["Feedback"])


class FeedbackCreate(BaseModel):
    ticket_id: int = Field(gt=0)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


def feedback_response(feedback: Feedback) -> dict:
    return {
        "id": feedback.id,
        "ticket_id": feedback.ticket_id,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "created_at": feedback.created_at,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_feedback(
    payload: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role.upper() != "CUSTOMER":
        raise HTTPException(
            status_code=403,
            detail="Only customers can submit feedback",
        )

    ticket = await db.get(Ticket, payload.ticket_id)

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket.customer_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only review your own tickets",
        )

    if ticket.status not in ("Resolved", "Closed"):
        raise HTTPException(
            status_code=400,
            detail="Feedback can only be submitted for resolved or closed tickets",
        )

    existing_result = await db.execute(
        select(Feedback).where(Feedback.ticket_id == payload.ticket_id)
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Feedback has already been submitted for this ticket",
        )

    feedback = Feedback(
        ticket_id=payload.ticket_id,
        rating=payload.rating,
        comment=payload.comment,
        created_at=datetime.utcnow(),
    )
    db.add(feedback)

    try:
        await db.commit()
        await db.refresh(feedback)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Feedback has already been submitted for this ticket",
        )

    return feedback_response(feedback)


@router.get("/ticket/{ticket_id}")
async def get_ticket_feedback(
    ticket_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)

    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    role = current_user.role.upper()

    if role != "ADMIN" and ticket.customer_id != current_user.id:
        if role != "AGENT":
            raise HTTPException(status_code=403, detail="Access denied")

        from app.models import Agent

        agent_result = await db.execute(
            select(Agent).where(Agent.user_id == current_user.id)
        )
        agent = agent_result.scalar_one_or_none()

        if not agent or ticket.assigned_agent_id != agent.id:
            raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(Feedback).where(Feedback.ticket_id == ticket_id)
    )
    feedback = result.scalar_one_or_none()

    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    return feedback_response(feedback)


@router.get("/")
async def list_feedback(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role.upper() != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Only administrators can view all feedback",
        )

    result = await db.execute(
        select(Feedback).order_by(Feedback.created_at.desc())
    )
    return [feedback_response(item) for item in result.scalars().all()]
