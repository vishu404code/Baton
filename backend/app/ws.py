"""Live room stream: WS /ws/rooms/{room_id}?token=bs_...&since_seq=N (API contract §9).

On connect: subscribe to the bus first (so nothing is missed), send `hello`, replay every
stored event with seq > since_seq from the database, then stream live events. Events are
de-duplicated by seq, so a client never sees one twice even if it arrives both ways.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.auth import user_from_token
from app.db import read_session
from app.models import Event, Room, RoomMember
from app.services import presence
from app.services.events import bus, event_out

router = APIRouter()

REPLAY_PAGE = 500


def _authorize(room_id: str, token: str | None) -> tuple[int, str | None, str | None]:
    """Return (close_code or 0, user_id, display_name)."""
    with read_session() as db:
        user = user_from_token(db, token)
        if user is None:
            return 4401, None, None
        try:
            rid = uuid.UUID(room_id)
        except ValueError:
            return 4404, None, None
        if db.get(Room, rid) is None:
            return 4404, None, None
        if db.get(RoomMember, (rid, user.id)) is None:
            return 4403, None, None
        return 0, str(user.id), user.display_name


def _load_events(room_id: str, since_seq: int) -> list[dict]:
    with read_session() as db:
        rows = db.execute(
            select(Event)
            .where(Event.room_id == uuid.UUID(room_id), Event.seq > since_seq)
            .order_by(Event.seq)
            .limit(REPLAY_PAGE)
        ).scalars().all()
        return [event_out(e) for e in rows]


def _latest_seq(room_id: str) -> int:
    with read_session() as db:
        return db.get(Room, uuid.UUID(room_id)).last_seq


@router.websocket("/ws/rooms/{room_id}")
async def room_stream(websocket: WebSocket, room_id: str, token: str | None = None, since_seq: int = 0) -> None:
    await websocket.accept()
    code, user_id, _ = await anyio.to_thread.run_sync(_authorize, room_id, token)
    if code:
        reasons = {4401: "bad or missing token", 4403: "not a member of this room", 4404: "unknown room"}
        await websocket.close(code=code, reason=reasons[code])
        return

    queue = bus.subscribe(room_id)
    came_online = presence.users.connect(room_id, user_id)
    last_sent = max(0, since_seq)
    send_lock = asyncio.Lock()

    async def send(msg: dict) -> None:
        async with send_lock:
            await websocket.send_text(json.dumps(msg))

    async def replay(after: int) -> None:
        nonlocal last_sent
        while True:
            events = await anyio.to_thread.run_sync(_load_events, room_id, after)
            for ev in events:
                if ev["seq"] > last_sent:
                    await send({"kind": "event", "event": ev})
                    last_sent = ev["seq"]
            if len(events) < REPLAY_PAGE:
                return
            after = events[-1]["seq"]

    async def pump() -> None:
        try:
            await _pump_loop()
        except (WebSocketDisconnect, RuntimeError):
            return  # socket closed while sending

    async def _pump_loop() -> None:
        nonlocal last_sent
        while True:
            msg = await queue.get()
            if msg.get("kind") == "event" and msg["event"].get("seq") is not None:
                seq = msg["event"]["seq"]
                if seq <= last_sent:
                    continue
                if seq > last_sent + 1:
                    await replay(last_sent)  # fill any gap from the database
                    if seq <= last_sent:
                        continue
                last_sent = seq
            await send(msg)

    async def receive() -> None:
        try:
            await _receive_loop()
        except WebSocketDisconnect:
            return

    async def _receive_loop() -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            kind = msg.get("kind")
            if kind == "ping":
                await send({"kind": "pong"})
            elif kind == "resume":
                await replay(int(msg.get("since_seq", last_sent)))

    try:
        snapshot = await anyio.to_thread.run_sync(presence.snapshot, room_id)
        latest = await anyio.to_thread.run_sync(_latest_seq, room_id)
        await send({"kind": "hello", "room_id": room_id, "latest_seq": latest, "presence": snapshot})
        if came_online:
            await presence.broadcast(room_id)
        await replay(last_sent)
        async with anyio.create_task_group() as tg:
            tg.start_soon(pump)
            await receive()
            tg.cancel_scope.cancel()
    except (WebSocketDisconnect, RuntimeError, ExceptionGroup):
        pass
    finally:
        bus.unsubscribe(room_id, queue)
        if presence.users.disconnect(room_id, user_id):
            try:
                await presence.broadcast(room_id)
            except Exception:
                pass
