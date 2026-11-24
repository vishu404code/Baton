"""Who is online. Users: open WebSocket connections (in memory). Agents: recent MCP activity.

`presence.changed` is ephemeral: it is pushed over the WebSocket (and in `hello`) but not
stored in the event log. A watcher re-checks rooms with live subscribers every couple of
seconds, so agents going quiet, claims starting or ending, and leases ticking are reflected
without any client polling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections import defaultdict
from datetime import timedelta

import anyio

from app.config import get_settings
from app.models import Agent, utcnow

log = logging.getLogger("baton.presence")


class _UserConnections:
    def __init__(self) -> None:
        self._counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._lock = threading.Lock()

    def connect(self, room_id: str, user_id: str) -> bool:
        """Returns True if this is the user's first connection to the room (they just came online)."""
        with self._lock:
            self._counts[room_id][user_id] += 1
            return self._counts[room_id][user_id] == 1

    def disconnect(self, room_id: str, user_id: str) -> bool:
        """Returns True if the user has no connections left (they just went offline)."""
        with self._lock:
            n = self._counts[room_id].get(user_id, 0) - 1
            if n <= 0:
                self._counts[room_id].pop(user_id, None)
                return True
            self._counts[room_id][user_id] = n
            return False

    def is_online(self, room_id: uuid.UUID | str, user_id: uuid.UUID | str) -> bool:
        with self._lock:
            return self._counts.get(str(room_id), {}).get(str(user_id), 0) > 0


users = _UserConnections()


def agent_online(agent: Agent) -> bool:
    if agent.revoked_at is not None or agent.last_seen_at is None:
        return False
    window = timedelta(seconds=get_settings().baton_agent_online_seconds)
    return utcnow() - agent.last_seen_at <= window


def snapshot(room_id: str | uuid.UUID) -> dict:
    """The GET /presence shape for one room."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import RoomMember, User
    from app.serializers import active_claim_for_agent, agent_out
    from app.services.events import iso

    rid = uuid.UUID(str(room_id))
    with SessionLocal() as db:
        members = db.execute(
            select(RoomMember, User).join(User, User.id == RoomMember.user_id).where(RoomMember.room_id == rid).order_by(RoomMember.joined_at)
        ).all()
        agents = db.execute(
            select(Agent, User.display_name)
            .join(User, User.id == Agent.user_id)
            .where(Agent.room_id == rid, Agent.revoked_at.is_(None))
            .order_by(Agent.created_at)
        ).all()
        agent_items = []
        for agent, owner in agents:
            a = agent_out(db, agent, owner)
            working = a["working_on"]
            if working:
                claim = active_claim_for_agent(db, agent.id)
                working = working | {"lease_expires_at": iso(claim[0].lease_expires_at) if claim else None}
            agent_items.append(
                {
                    "agent_id": a["id"],
                    "name": a["name"],
                    "tool": a["tool"],
                    "role": a["role"],
                    "color": a["color"],
                    "user_id": a["user_id"],
                    "user_name": a["user_name"],
                    "online": a["online"],
                    "last_seen_at": a["last_seen_at"],
                    "working_on": working,
                }
            )
        return {
            "users": [
                {
                    "user_id": str(u.id),
                    "display_name": u.display_name,
                    "room_role": m.role,
                    "online": users.is_online(rid, u.id),
                }
                for m, u in members
            ],
            "agents": agent_items,
        }


# --- Broadcasting -------------------------------------------------------------------------

_last_sent: dict[str, str] = {}


async def broadcast(room_id: str, *, only_if_changed: bool = False) -> None:
    from app.services.events import bus, iso

    snap = await anyio.to_thread.run_sync(snapshot, room_id)
    # Compare without lease times, which change on every heartbeat (task.heartbeat covers those).
    key = json.dumps(
        {"u": [(u["user_id"], u["online"]) for u in snap["users"]],
         "a": [(a["agent_id"], a["online"], (a["working_on"] or {}).get("task_id")) for a in snap["agents"]]},
        sort_keys=True,
    )
    if only_if_changed and _last_sent.get(room_id) == key:
        return
    _last_sent[room_id] = key
    bus.publish(room_id, {"kind": "event", "event": {
        "id": None, "room_id": room_id, "seq": None, "type": "presence.changed",
        "actor": {"kind": "system", "id": None, "name": "Baton"}, "summary": "Presence changed",
        "payload": snap, "created_at": iso(utcnow()),
    }})


async def watcher(interval: float = 2.0) -> None:
    from app.services.events import bus

    while True:
        await asyncio.sleep(interval)
        for room_id in bus.rooms_with_subscribers():
            try:
                await broadcast(room_id, only_if_changed=True)
            except Exception:
                log.exception("presence broadcast failed for room %s", room_id)
