"""Append-only event log with gap-free per-room sequence numbers, plus an in-process pub/sub.

`append_event` must be called inside the same transaction as the change it describes.
It locks the room row to allocate the next `seq`. Events are broadcast to WebSocket
subscribers only after the transaction commits (see the after_commit hook below), so
clients never see an event for a change that rolled back.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import defaultdict
from collections.abc import Iterable

from fastapi.encoders import jsonable_encoder
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Room, utcnow

SYSTEM_ACTOR = {"kind": "system", "id": None, "name": "Baton"}


def iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def event_out(ev: Event) -> dict:
    return {
        "id": str(ev.id),
        "room_id": str(ev.room_id),
        "seq": ev.seq,
        "type": ev.type,
        "actor": ev.actor,
        "summary": ev.summary,
        "payload": ev.payload,
        "created_at": iso(ev.created_at),
    }


def append_event(
    db: Session,
    room_id: uuid.UUID,
    type: str,
    actor: dict,
    summary: str,
    payload: dict | None = None,
    record_ids: Iterable[uuid.UUID | str] = (),
) -> Event:
    room = db.execute(select(Room).where(Room.id == room_id).with_for_update()).scalar_one()
    room.last_seq += 1
    ev = Event(
        room_id=room_id,
        seq=room.last_seq,
        type=type,
        actor=jsonable_encoder(actor),
        summary=summary,
        payload=jsonable_encoder(payload or {}),
        record_ids=[str(r) for r in record_ids],
        created_at=utcnow(),
    )
    db.add(ev)
    db.flush()
    db.info.setdefault("pending_events", []).append(ev)
    return ev


class EventBus:
    """Fan-out of committed events (and ephemeral messages like presence) to WebSocket queues."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = threading.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, room_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subs[room_id].add(q)
        return q

    def unsubscribe(self, room_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs[room_id].discard(q)

    def rooms_with_subscribers(self) -> list[str]:
        with self._lock:
            return [r for r, qs in self._subs.items() if qs]

    def publish(self, room_id: str, message: dict) -> None:
        """Thread-safe: may be called from sync request handlers running in the threadpool."""
        with self._lock:
            queues = list(self._subs.get(room_id, ()))
        if not queues or self.loop is None:
            return
        for q in queues:
            self.loop.call_soon_threadsafe(_put_nowait, q, message)


def _put_nowait(q: asyncio.Queue, message: dict) -> None:
    try:
        q.put_nowait(message)
    except asyncio.QueueFull:
        pass  # A stuck client reconnects with since_seq and replays from the database.


bus = EventBus()


@sa_event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    pending = session.info.pop("pending_events", [])
    for ev in pending:
        bus.publish(str(ev.room_id), {"kind": "event", "event": event_out(ev)})


@sa_event.listens_for(Session, "after_rollback")
def _drop_after_rollback(session: Session) -> None:
    session.info.pop("pending_events", None)
