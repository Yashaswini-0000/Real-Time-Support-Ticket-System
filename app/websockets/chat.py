
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import select

from app.auth.security import SECRET_KEY, ALGORITHM
from app.database import AsyncSessionLocal
from app.models import User, Ticket, Message, Agent

router = APIRouter(tags=["WebSocket Chat"])


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, dict[WebSocket, dict]] = {}

    async def connect(self, ticket_id: int, websocket: WebSocket, user: dict):
        await websocket.accept()
        self.active_connections.setdefault(ticket_id, {})[websocket] = user

    def disconnect(self, ticket_id: int, websocket: WebSocket):
        connections = self.active_connections.get(ticket_id, {})
        connections.pop(websocket, None)

        if not connections:
            self.active_connections.pop(ticket_id, None)

    async def broadcast(self, ticket_id: int, data: dict):
        connections = self.active_connections.get(ticket_id, {})

        for connection, user in list(connections.items()):
            if data.get("is_internal_note") and user["role"] not in (
                "ADMIN", "AGENT"
            ):
                continue

            try:
                await connection.send_json(data)
            except Exception:
                self.disconnect(ticket_id, connection)


manager = ConnectionManager()


async def authenticate_user(token: str):
    try:
        payload = jwt.decode(
            token, SECRET_KEY, algorithms=[ALGORITHM]
        )
        user_id = int(payload["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        return None

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)

        if not user or not user.is_active:
            return None

        return {
            "id": user.id,
            "role": user.role.upper(),
        }


async def can_access_ticket(ticket_id: int, user: dict) -> bool:
    async with AsyncSessionLocal() as db:
        ticket = await db.get(Ticket, ticket_id)

        if not ticket:
            return False

        role = user["role"]

        if role == "ADMIN":
            return True

        if role == "CUSTOMER":
            return ticket.customer_id == user["id"]

        if role == "AGENT":
            if ticket.assigned_agent_id is None:
                return False

            agent = await db.get(Agent, ticket.assigned_agent_id)
            return bool(agent and agent.user_id == user["id"])

        return False


@router.websocket("/ws/tickets/{ticket_id}")
async def ticket_chat(websocket: WebSocket, ticket_id: int):
    token = websocket.query_params.get("token")

    if not token:
        await websocket.close(
            code=1008, reason="Authentication required"
        )
        return

    user = await authenticate_user(token)

    if not user:
        await websocket.close(
            code=1008, reason="Invalid authentication"
        )
        return

    if not await can_access_ticket(ticket_id, user):
        await websocket.close(
            code=1008, reason="Ticket access denied"
        )
        return

    async with AsyncSessionLocal() as db:
        ticket = await db.get(Ticket, ticket_id)

        if not ticket:
            await websocket.close(
                code=1008, reason="Ticket not found"
            )
            return

        if ticket.status == "Closed":
            await websocket.close(
                code=1008, reason="Ticket is closed"
            )
            return

    role = user["role"]
    await manager.connect(ticket_id, websocket, user)

    try:
        # Send the latest 50 messages, oldest first.
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Message)
                .where(Message.ticket_id == ticket_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(50)
            )
            messages = list(reversed(result.scalars().all()))

            for msg in messages:
                if (
                    msg.is_internal_note
                    and role not in ("ADMIN", "AGENT")
                ):
                    continue

                await websocket.send_json({
                    "type": "message",
                    "id": msg.id,
                    "ticket_id": msg.ticket_id,
                    "sender_id": msg.sender_id,
                    "sender_role": msg.sender_role,
                    "message": msg.message,
                    "is_internal_note": msg.is_internal_note,
                    "created_at": (
                        msg.created_at.isoformat()
                        if msg.created_at else None
                    ),
                })

        while True:
            data = await websocket.receive_json()

            if not isinstance(data, dict):
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid message format",
                })
                continue

            message_text = data.get("message", "")
            if not isinstance(message_text, str):
                await websocket.send_json({
                    "type": "error",
                    "message": "Message must be text",
                })
                continue

            message_text = message_text.strip()
            is_internal_note = data.get("is_internal_note", False)

            if not message_text or len(message_text) > 2000:
                await websocket.send_json({
                    "type": "error",
                    "message": "Message must contain 1–2000 characters",
                })
                continue

            if not isinstance(is_internal_note, bool):
                await websocket.send_json({
                    "type": "error",
                    "message": "is_internal_note must be true or false",
                })
                continue

            if (
                is_internal_note
                and role not in ("ADMIN", "AGENT")
            ):
                await websocket.send_json({
                    "type": "error",
                    "message": "Only agents and admins can add internal notes",
                })
                continue

            # Recheck ticket access and status for every message.
            async with AsyncSessionLocal() as db:
                ticket = await db.get(Ticket, ticket_id)

                if not ticket or ticket.status == "Closed":
                    await websocket.send_json({
                        "type": "error",
                        "message": "Ticket is unavailable or closed",
                    })
                    break

                if not await can_access_ticket(ticket_id, user):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Ticket access denied",
                    })
                    break

                msg = Message(
                    ticket_id=ticket_id,
                    sender_id=user["id"],
                    sender_role=role,
                    message=message_text,
                    is_internal_note=is_internal_note,
                    is_read=False,
                )
                db.add(msg)

                if (
                    role == "AGENT"
                    and not is_internal_note
                    and ticket.first_response_at is None
                ):
                    ticket.first_response_at = datetime.now(timezone.utc)

                await db.commit()
                await db.refresh(msg)

                outgoing = {
                    "type": "message",
                    "id": msg.id,
                    "ticket_id": ticket_id,
                    "sender_id": user["id"],
                    "sender_role": role,
                    "message": message_text,
                    "is_internal_note": is_internal_note,
                    "created_at": (
                        msg.created_at.isoformat()
                        if msg.created_at else None
                    ),
                }

            # The manager filters internal notes by each connection's role.
            await manager.broadcast(ticket_id, outgoing)

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ticket_id, websocket)
 