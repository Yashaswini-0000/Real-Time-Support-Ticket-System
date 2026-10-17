
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_roles
from app.database import get_db
from app.models import Agent, User

router = APIRouter(prefix="/agents", tags=["Agents"])


class AgentCreate(BaseModel):
    user_id: int = Field(gt=0)
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    max_open_tickets: int = Field(default=10, ge=1, le=100)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    email: EmailStr | None = None
    max_open_tickets: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None


class AvailabilityUpdate(BaseModel):
    availability: str = Field(pattern="^(Online|Offline)$")


def agent_response(agent: Agent) -> dict:
    return {
        "id": agent.id,
        "user_id": agent.user_id,
        "name": agent.name,
        "email": agent.email,
        "availability": agent.availability,
        "max_open_tickets": agent.max_open_tickets,
        "is_active": agent.is_active,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_agent(
    data: AgentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN")),
):
    user = await db.get(User, data.user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Cannot create an agent for an inactive user")

    existing = await db.execute(
        select(Agent).where(
            (Agent.user_id == data.user_id) | (Agent.email == data.email)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Agent already exists for this user or email",
        )

    user.role = "AGENT"

    agent = Agent(
        user_id=user.id,
        name=data.name,
        email=str(data.email),
        max_open_tickets=data.max_open_tickets,
        availability="Offline",
        is_active=True,
    )

    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent_response(agent)


@router.get("/")
async def list_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN", "AGENT")),
):
    result = await db.execute(select(Agent).order_by(Agent.id))
    return [agent_response(agent) for agent in result.scalars().all()]


@router.get("/me")
async def get_my_agent_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("AGENT")),
):
    result = await db.execute(
        select(Agent).where(Agent.user_id == current_user.id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    return agent_response(agent)


@router.put("/me/availability")
async def update_my_availability(
    data: AvailabilityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("AGENT")),
):
    result = await db.execute(
        select(Agent).where(Agent.user_id == current_user.id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    if not agent.is_active:
        raise HTTPException(status_code=403, detail="Agent account is inactive")

    agent.availability = data.availability
    await db.commit()
    await db.refresh(agent)

    return agent_response(agent)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN", "AGENT")),
):
    agent = await db.get(Agent, agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return agent_response(agent)


@router.put("/{agent_id}")
async def update_agent(
    agent_id: int,
    data: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN")),
):
    agent = await db.get(Agent, agent_id)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    updates = data.model_dump(exclude_unset=True)

    if "email" in updates and updates["email"] is not None:
        updates["email"] = str(updates["email"])
        result = await db.execute(
            select(Agent).where(
                Agent.email == updates["email"],
                Agent.id != agent_id,
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already in use")

    for field, value in updates.items():
        setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return agent_response(agent)
