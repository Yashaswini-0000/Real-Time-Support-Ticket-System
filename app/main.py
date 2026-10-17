
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models
from app.routers import auth, tickets, messages, agents, categories, notifications
from app.routers.feedback import router as feedback_router
from app.websockets.chat import router as chat_router
from app.routers import reports
from app.services.sla_monitor import(
    start_sla_scheduler,
    stop_sla_scheduler,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start and stop background services with the application."""
    start_sla_scheduler()
    try:
        yield
    finally:
        stop_sla_scheduler()


app = FastAPI(
    title="Real-Time Support Ticket System",
    version="1.0.0",
    description="API for managing support tickets, agents, and customers",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {
        "message": "Real-Time Support Ticket System API is running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Register API routers
app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(messages.router)
app.include_router(agents.router)
app.include_router(categories.router)
app.include_router(chat_router)
app.include_router(notifications.router)
app.include_router(feedback_router)
app.include_router(reports.router)
