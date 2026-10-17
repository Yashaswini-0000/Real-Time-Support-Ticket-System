
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.security import SECRET_KEY, ALGORITHM
from app.database import get_db, AsyncSessionLocal
from app.models import Notification, User

router = APIRouter(tags=["Notifications"])


class NotificationConnectionManager:
    def __init__(self):
        self.connections: dict[int, set[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        connections = self.connections.get(user_id)
        if connections:
            connections.discard(websocket)
            if not connections:
                self.connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, data: dict):
        for websocket in list(self.connections.get(user_id, set())):
            try:
                await websocket.send_json(data)
            except Exception:
                self.disconnect(user_id, websocket)


manager = NotificationConnectionManager()


def notification_response(item: Notification) -> dict:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "ticket_id": item.ticket_id,
        "title": item.title,
        "message": item.message,
        "is_read": item.is_read,
        "created_at": (
            item.created_at.isoformat() if item.created_at else None
        ),
    }


async def create_notification(
    user_id: int,
    title: str,
    message: str,
    ticket_id: int | None = None,
) -> dict:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if not user or not user.is_active:
            raise ValueError("Notification recipient does not exist or is inactive")

        item = Notification(
            user_id=user_id,
            ticket_id=ticket_id,
            title=title,
            message=message,
            is_read=False,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        response = notification_response(item)

    await manager.send_to_user(
        user_id,
        {"type": "notification", "notification": response},
    )
    return response


@router.get("/notifications")
async def list_notifications(
    unread_only: bool = False,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if skip < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid pagination values")

    query = select(Notification).where(
        Notification.user_id == current_user.id
    )

    if unread_only:
        query = query.where(Notification.is_read.is_(False))

    result = await db.execute(
        query.order_by(
            Notification.created_at.desc(),
            Notification.id.desc(),
        ).offset(skip).limit(limit)
    )
    return [notification_response(item) for item in result.scalars().all()]


@router.put("/notifications/{notification_id}/read")
@router.patch("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await db.get(Notification, notification_id)

    if not item or item.user_id != current_user.id:
        raise HTTPException(404, "Notification not found")

    item.is_read = True
    await db.commit()
    await db.refresh(item)
    return notification_response(item)


@router.put("/notifications/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    )

    items = result.scalars().all()
    for item in items:
        item.is_read = True

    await db.commit()

    return {
        "message": "All notifications marked as read",
        "updated_count": len(items),
    }


@router.websocket("/ws/notifications")
async def notification_websocket(websocket: WebSocket):
    token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=1008)
        return

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        await websocket.close(code=1008)
        return

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if not user or not user.is_active:
            await websocket.close(code=1008)
            return

    await manager.connect(user_id, websocket)

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.is_read.is_(False),
                )
                .order_by(Notification.created_at.desc())
                .limit(50)
            )

            for item in result.scalars().all():
                await websocket.send_json({
                    "type": "notification",
                    "notification": notification_response(item),
                })

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(user_id, websocket)
