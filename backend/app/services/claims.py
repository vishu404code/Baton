"""Claims with leases. One agent holds a task exclusively until the lease runs out.

The database enforces exclusivity (partial unique index on active claims per task),
so two agents can never hold the same task even under a race.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AgentError
from app.models import Agent, Claim, Record, Room, User, utcnow
from app.serializers import actor_agent
from app.services.events import SYSTEM_ACTOR, append_event, iso
from app.services.ledger import current_revision, label, output_of, record_ref, resolve_record

CLAIMABLE = ("open", "stale")


def lease_minutes(room: Room) -> int:
    return int((room.settings or {}).get("lease_minutes", 15))


def claim_out(claim: Claim, agent: Agent, owner_name: str | None) -> dict:
    return {
        "id": str(claim.id),
        "task_id": str(claim.task_id),
        "agent": actor_agent(agent, owner_name),
        "status": claim.status,
        "lease_expires_at": iso(claim.lease_expires_at),
        "is_redo": claim.is_redo,
        "created_at": iso(claim.created_at),
    }


def _owner_name(db: Session, agent: Agent) -> str:
    return db.get(User, agent.user_id).display_name


def _restore_task_status(task: Record, claim: Claim) -> None:
    if task.status == "claimed":
        task.status = "stale" if claim.is_redo else "open"


def expire_claim(db: Session, claim: Claim) -> None:
    task = db.get(Record, claim.task_id)
    agent = db.get(Agent, claim.agent_id)
    claim.status = "expired"
    claim.ended_at = utcnow()
    _restore_task_status(task, claim)
    append_event(
        db,
        task.room_id,
        "claim.expired",
        SYSTEM_ACTOR,
        f"{agent.name}'s lease on {label(task)} expired; the task is available again",
        {"task": record_ref(task), "agent": actor_agent(agent, _owner_name(db, agent)), "expired_at": iso(claim.lease_expires_at)},
        record_ids=[task.id],
    )


def expire_due(db: Session) -> int:
    """Expire every active claim whose lease has run out. Called by the background sweeper."""
    due = db.execute(
        select(Claim).where(Claim.status == "active", Claim.lease_expires_at <= utcnow()).with_for_update(skip_locked=True)
    ).scalars().all()
    for claim in due:
        expire_claim(db, claim)
    return len(due)


def active_claim(db: Session, task: Record, *, lock: bool = False) -> Claim | None:
    """The task's active claim, expiring it first if its lease has run out."""
    stmt = select(Claim).where(Claim.task_id == task.id, Claim.status == "active")
    if lock:
        stmt = stmt.with_for_update()
    claim = db.execute(stmt).scalar_one_or_none()
    if claim is not None and claim.lease_expires_at <= utcnow():
        expire_claim(db, claim)
        db.flush()
        return None
    return claim


def task_role(db: Session, task: Record) -> str | None:
    rev = current_revision(db, task)
    return (rev.content or {}).get("role") if rev else None


def role_problem(db: Session, agent: Agent, task: Record) -> str | None:
    if agent.role == "observer":
        return f"permission: {agent.name} is an observer and can only read."
    needed = task_role(db, task)
    if needed and needed != agent.role:
        return f"permission: {label(task)} needs a {needed}; {agent.name} is a {agent.role}."
    return None


def claim_task(db: Session, agent: Agent, task_ref: str) -> Claim:
    task = resolve_record(db, agent.room_id, task_ref, "task")
    room = db.get(Room, agent.room_id)
    problem = role_problem(db, agent, task)
    if problem:
        raise AgentError("forbidden", problem)

    existing = active_claim(db, task, lock=True)
    if existing is not None:
        if existing.agent_id == agent.id:
            return existing  # claiming twice is harmless; use heartbeat to extend
        holder = db.get(Agent, existing.agent_id)
        raise AgentError(
            "conflict",
            f"already claimed by {holder.name} until {iso(existing.lease_expires_at)}; pick another task with list_tasks.",
        )
    if task.status not in CLAIMABLE:
        reason = {
            "in_review": "its output is waiting for human approval",
            "approved": "it is already approved",
            "rejected": "it was rejected",
            "claimed": "it is claimed",
        }.get(task.status, task.status)
        raise AgentError("conflict", f"{label(task)} can't be claimed: {reason}. Call list_tasks for open work.")

    review_of = (current_revision(db, task).content or {}).get("review_of_task_id")
    if review_of:
        reviewed = db.get(Record, uuid.UUID(review_of))
        if reviewed is None or output_of(db, reviewed) is None:
            raise AgentError(
                "conflict",
                f"{label(task)} reviews {label(reviewed) if reviewed else 'a task'}, which has no draft yet. Try again later.",
            )

    now = utcnow()
    claim = Claim(
        task_id=task.id,
        agent_id=agent.id,
        status="active",
        lease_expires_at=now + timedelta(minutes=lease_minutes(room)),
        is_redo=task.status == "stale",
        created_at=now,
    )
    db.add(claim)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AgentError("conflict", f"{label(task)} was just claimed by another agent; pick another task.")
    task.status = "claimed"
    owner = _owner_name(db, agent)
    append_event(
        db,
        room.id,
        "task.claimed",
        actor_agent(agent, owner),
        f"{agent.name} claimed {label(task)} \"{task.title}\""
        + (" (redo of stale work)" if claim.is_redo else ""),
        {"task": record_ref(task), "claim": claim_out(claim, agent, owner)},
        record_ids=[task.id],
    )
    return claim


def _held_claim(db: Session, agent: Agent, task: Record) -> Claim:
    claim = active_claim(db, task, lock=True)
    if claim is None:
        raise AgentError("conflict", f"not claimed: you don't hold {label(task)} (or the lease expired). Call claim_task(\"{label(task)}\").")
    if claim.agent_id != agent.id:
        holder = db.get(Agent, claim.agent_id)
        raise AgentError("conflict", f"{label(task)} is held by {holder.name}, not you.")
    return claim


def heartbeat(db: Session, agent: Agent, task_ref: str) -> Claim:
    task = resolve_record(db, agent.room_id, task_ref, "task")
    claim = _held_claim(db, agent, task)
    room = db.get(Room, agent.room_id)
    claim.lease_expires_at = utcnow() + timedelta(minutes=lease_minutes(room))
    append_event(
        db,
        room.id,
        "task.heartbeat",
        actor_agent(agent, _owner_name(db, agent)),
        f"{agent.name} extended its lease on {label(task)}",
        {"task": record_ref(task), "lease_expires_at": iso(claim.lease_expires_at)},
        record_ids=[task.id],
    )
    return claim


def end_claim(db: Session, agent: Agent, task: Record, claim: Claim, reason: str) -> None:
    claim.status = "released"
    claim.ended_at = utcnow()
    if reason == "released":
        _restore_task_status(task, claim)
    append_event(
        db,
        task.room_id,
        "task.released",
        actor_agent(agent, _owner_name(db, agent)),
        f"{agent.name} released {label(task)}" + (" after submitting" if reason == "submitted" else ""),
        {"task": record_ref(task), "agent": actor_agent(agent, _owner_name(db, agent)), "reason": reason},
        record_ids=[task.id],
    )


def release_task(db: Session, agent: Agent, task_ref: str) -> None:
    task = resolve_record(db, agent.room_id, task_ref, "task")
    claim = _held_claim(db, agent, task)
    end_claim(db, agent, task, claim, "released")
