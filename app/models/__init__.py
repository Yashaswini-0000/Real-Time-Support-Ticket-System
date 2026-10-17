
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(20), default="Customer", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    agent_profile: Mapped["Agent | None"] = relationship(
        back_populates="user",
        uselist=False,
    )
    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="customer",
        foreign_keys="Ticket.customer_id",
    )


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="category"
    )


class AgentCategory(Base):
    __tablename__ = "agent_categories"
    __table_args__ = (
        UniqueConstraint("agent_id", "category_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE")
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE")
    )


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    availability: Mapped[str] = mapped_column(
        String(20), default="Offline", nullable=False
    )
    max_open_tickets: Mapped[int] = mapped_column(
        Integer, default=10, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    user: Mapped["User"] = relationship(
        back_populates="agent_profile"
    )
    assigned_tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="assigned_agent"
    )


class SLAPolicy(Base, TimestampMixin):
    __tablename__ = "sla_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    priority: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False
    )
    first_response_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    resolution_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_number: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False
    )
    assigned_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    subject: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    priority: Mapped[str] = mapped_column(
        String(20), default="Medium", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), default="Open", nullable=False
    )

    first_response_due: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    resolution_due: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    sla_breached: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    reopen_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    customer: Mapped["User"] = relationship(
        back_populates="tickets",
        foreign_keys=[customer_id],
    )
    category: Mapped["Category"] = relationship(
        back_populates="tickets"
    )
    assigned_agent: Mapped["Agent | None"] = relationship(
        back_populates="assigned_tickets"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="ticket"
    )
    status_history: Mapped[list["StatusHistory"]] = relationship(
        back_populates="ticket"
    )
    feedback: Mapped["Feedback | None"] = relationship(
        back_populates="ticket",
        uselist=False,
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id"), nullable=False
    )
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    sender_role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal_note: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    ticket: Mapped["Ticket"] = relationship(
        back_populates="messages"
    )


class StatusHistory(Base):
    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id"), nullable=False
    )
    old_status: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    new_status: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    changed_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    ticket: Mapped["Ticket"] = relationship(
        back_populates="status_history"
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id"),
        unique=True,
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    ticket: Mapped["Ticket"] = relationship(
        back_populates="feedback"
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    ticket_id: Mapped[int | None] = mapped_column(
        ForeignKey("tickets.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
