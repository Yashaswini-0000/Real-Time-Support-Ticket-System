
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Category, Ticket, SLAPolicy
from app.auth.dependencies import get_current_user, require_roles

router = APIRouter(tags=["Categories and SLA Policies"])


# ---------- Schemas ----------

class CategoryCreate(BaseModel):
    category_name: str = Field(min_length=2, max_length=100)
    description: str | None = None


class CategoryUpdate(BaseModel):
    category_name: str = Field(min_length=2, max_length=100)
    description: str | None = None
    is_active: bool = True


class SLAPolicyUpdate(BaseModel):
    first_response_minutes: int = Field(gt=0)
    resolution_minutes: int = Field(gt=0)


def category_response(category: Category):
    return {
        "id": category.id,
        "category_name": category.category_name,
        "description": category.description,
        "is_active": category.is_active,
    }


def sla_response(policy: SLAPolicy):
    return {
        "id": policy.id,
        "priority": policy.priority,
        "first_response_minutes": policy.first_response_minutes,
        "resolution_minutes": policy.resolution_minutes,
    }


# ---------- Category APIs ----------

@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def create_category(
    data: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles("ADMIN")),
):
    name = data.category_name.strip()

    if not name:
        raise HTTPException(422, "Category name cannot be empty")

    existing = await db.execute(
        select(Category).where(
            func.lower(Category.category_name) == name.lower()
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Category name already exists")

    category = Category(
        category_name=name,
        description=data.description,
        is_active=True,
    )
    db.add(category)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Category name already exists")

    await db.refresh(category)
    return category_response(category)


@router.get("/categories")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(Category).order_by(Category.id)
    )
    return [category_response(c) for c in result.scalars().all()]


@router.put("/categories/{category_id}")
async def update_category(
    category_id: int,
    data: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles("ADMIN")),
):
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(404, "Category not found")

    name = data.category_name.strip()
    if not name:
        raise HTTPException(422, "Category name cannot be empty")

    existing = await db.execute(
        select(Category).where(
            func.lower(Category.category_name) == name.lower(),
            Category.id != category_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Category name already exists")

    category.category_name = name
    category.description = data.description
    category.is_active = data.is_active

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Category name already exists")

    await db.refresh(category)
    return category_response(category)


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles("ADMIN")),
):
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(404, "Category not found")

    result = await db.execute(
        select(Ticket.id).where(
            Ticket.category_id == category_id,
            Ticket.status.notin_(["Resolved", "Closed"]),
        ).limit(1)
    )

    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            409, "Cannot delete a category with open tickets"
        )

    await db.delete(category)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            409, "Category is referenced by existing tickets"
        )

    return {"message": "Category deleted successfully"}


# ---------- SLA Policy APIs ----------

@router.get("/sla-policies")
async def list_sla_policies(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(SLAPolicy).order_by(SLAPolicy.id)
    )
    policies = result.scalars().all()

    if not policies:
        defaults = [
            ("Low", 1440, 4320),
            ("Medium", 480, 2880),
            ("High", 120, 1440),
            ("Urgent", 30, 480),
        ]

        policies = [
            SLAPolicy(
                priority=priority,
                first_response_minutes=response_minutes,
                resolution_minutes=resolution_minutes,
            )
            for priority, response_minutes, resolution_minutes in defaults
        ]

        db.add_all(policies)

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            result = await db.execute(
                select(SLAPolicy).order_by(SLAPolicy.id)
            )
            policies = result.scalars().all()
        else:
            for policy in policies:
                await db.refresh(policy)

    return [sla_response(policy) for policy in policies]


@router.put("/sla-policies/{priority}")
async def update_sla_policy(
    priority: str,
    data: SLAPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles("ADMIN")),
):
    result = await db.execute(
        select(SLAPolicy).where(
            func.lower(SLAPolicy.priority) == priority.strip().lower()
        )
    )
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(
            404,
            "SLA policy not found. Call GET /sla-policies first.",
        )

    policy.first_response_minutes = data.first_response_minutes
    policy.resolution_minutes = data.resolution_minutes

    await db.commit()
    await db.refresh(policy)
    return sla_response(policy)
