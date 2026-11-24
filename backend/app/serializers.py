"""Turn ORM rows into the JSON shapes defined in docs/API_CONTRACT.md §1."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Agent, Approval, Claim, Record, Room, RoomMember, User, utcnow
from app.services import presence
from app.services.events import iso

AGENT_COLORS = ["#F59E0B", "#22D3EE", "#A78BFA", "#34D399", "#F472B6", "#60A5FA", "#FB923C", "#E879F9"]


def user_out(user: User) -> dict:
    return {"id": str(user.id), "display_name": user.display_name, "created_at": iso(user.created_at)}


def actor_user(user: User, room_role: str | None = None) -> dict:
    return {"kind": "user", "id": str(user.id), "name": user.display_name, "room_role": room_role}


def actor_agent(agent: Agent, user_name: str | None = None) -> dict:
    return {
        "kind": "agent",
        "id": str(agent.id),
        "name": agent.name,
        "tool": agent.tool,
        "role": agent.role,
        "color": agent.color,
        "user_id": str(agent.user_id),
        "user_name": user_name,
    }


def room_counts(db: Session, room_id: uuid.UUID) -> dict:
    def count(stmt) -> int:
        return db.execute(stmt).scalar_one()

    return {
        "members": count(select(func.count()).select_from(RoomMember).where(RoomMember.room_id == room_id)),
        "agents": count(
            select(func.count()).select_from(Agent).where(Agent.room_id == room_id, Agent.revoked_at.is_(None))
        ),
        "open_tasks": count(
            select(func.count()).select_from(Record).where(
                Record.room_id == room_id, Record.type == "task", Record.status == "open"
            )
        ),
        "stale": count(
            select(func.count()).select_from(Record).where(
                Record.room_id == room_id, Record.type == "task", Record.status == "stale"
            )
        ),
        "pending_approvals": count(
            select(func.count()).select_from(Approval).where(Approval.room_id == room_id, Approval.status == "pending")
        ),
    }


def room_summary_out(db: Session, room: Room, my_role: str) -> dict:
    return {
        "id": str(room.id),
        "name": room.name,
        "my_role": my_role,
        "unread_hint": False,
        "counts": room_counts(db, room.id),
        "latest_seq": room.last_seq,
    }


def room_out(db: Session, room: Room, my_role: str) -> dict:
    return {
        "id": str(room.id),
        "name": room.name,
        "invite_code": room.invite_code,
        "owner_id": str(room.owner_id),
        "my_role": my_role,
        "settings": room.settings,
        "counts": room_counts(db, room.id),
        "latest_seq": room.last_seq,
        "created_at": iso(room.created_at),
    }


def member_out(db: Session, member: RoomMember, user: User) -> dict:
    agent_ids = db.execute(
        select(Agent.id).where(
            Agent.room_id == member.room_id, Agent.user_id == member.user_id, Agent.revoked_at.is_(None)
        )
    ).scalars()
    return {
        "user": user_out(user),
        "role": member.role,
        "joined_at": iso(member.joined_at),
        "online": presence.users.is_online(member.room_id, member.user_id),
        "agent_ids": [str(a) for a in agent_ids],
    }


def active_claim_for_agent(db: Session, agent_id: uuid.UUID) -> tuple[Claim, Record] | None:
    row = db.execute(
        select(Claim, Record)
        .join(Record, Record.id == Claim.task_id)
        .where(Claim.agent_id == agent_id, Claim.status == "active", Claim.lease_expires_at > utcnow())
        .order_by(Claim.created_at.desc())
    ).first()
    return (row[0], row[1]) if row else None


def _runnable(agent: Agent) -> bool:
    """True when Baton can run this agent itself (its AI provider is set up)."""
    if not agent.provider or agent.revoked_at is not None:
        return False
    from app.llm import registry, store

    p = registry.PROVIDERS.get(agent.provider)
    return p is not None and (not p.info.needs_key or bool(store.get(p.info)["api_key"]))


def agent_out(db: Session, agent: Agent, user_name: str | None = None) -> dict:
    if user_name is None:
        user_name = db.get(User, agent.user_id).display_name
    working = active_claim_for_agent(db, agent.id)
    return {
        "id": str(agent.id),
        "room_id": str(agent.room_id),
        "user_id": str(agent.user_id),
        "user_name": user_name,
        "name": agent.name,
        "tool": agent.tool,
        "role": agent.role,
        "color": agent.color,
        "provider": agent.provider,
        "model": agent.model,
        "runnable": _runnable(agent),
        "online": presence.agent_online(agent),
        "last_seen_at": iso(agent.last_seen_at),
        "working_on": (
            {"task_id": str(working[1].id), "label": f"Task {working[1].number}", "title": working[1].title}
            if working
            else None
        ),
        "revoked": agent.revoked_at is not None,
        "created_at": iso(agent.created_at),
    }
