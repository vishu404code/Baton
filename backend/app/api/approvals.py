"""Human approval of agent work (contract §7). Redone stale work always waits here."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, get_membership, is_mentor
from app.db import get_db
from app.errors import ApiError, forbidden, not_found
from app.models import Agent, Approval, Claim, Record, Revision, RoomMember, User, utcnow
from app.record_views import approval_out, record_out, revision_out
from app.schemas import _In
from app.serializers import actor_user
from app.services import ledger
from app.services.events import append_event

router = APIRouter(prefix="/api", tags=["approvals"])


class DecideIn(_In):
    decision: Literal["approved", "rejected"]
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _comment_when_rejecting(self):
        if self.decision == "rejected" and not (self.comment or "").strip():
            raise ValueError("a comment is required when rejecting")
        return self


def can_decide(db: Session, member: RoomMember) -> bool:
    """Owners and mentors, or members who own a reviewer agent in this room."""
    if is_mentor(member):
        return True
    return db.execute(
        select(Agent.id).where(
            Agent.room_id == member.room_id, Agent.user_id == member.user_id,
            Agent.role == "reviewer", Agent.revoked_at.is_(None),
        )
    ).first() is not None


def _previous_revision(db: Session, rev: Revision) -> Revision | None:
    if rev.number <= 1:
        return None
    return db.execute(
        select(Revision).where(Revision.record_id == rev.record_id, Revision.number == rev.number - 1)
    ).scalar_one_or_none()


@router.get("/rooms/{room_id}/approvals")
def list_approvals(
    room_id: uuid.UUID,
    status: Literal["pending", "approved", "rejected", "all"] = "pending",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_membership(db, room_id, user)
    stmt = select(Approval).where(Approval.room_id == room_id)
    if status != "all":
        stmt = stmt.where(Approval.status == status)
    items = []
    for a in db.execute(stmt.order_by(Approval.requested_at.desc())).scalars():
        rev = db.get(Revision, a.revision_id)
        prev = _previous_revision(db, rev)
        items.append(approval_out(db, a) | {
            "revision": revision_out(db, rev),
            "previous_revision": revision_out(db, prev) if prev else None,
        })
    return {"approvals": items}


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: uuid.UUID, body: DecideIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    approval = db.execute(select(Approval).where(Approval.id == approval_id).with_for_update()).scalar_one_or_none()
    if approval is None:
        raise not_found("Approval not found.")
    room, member = get_membership(db, approval.room_id, user)
    if not can_decide(db, member):
        raise forbidden("Only the owner, a mentor, or a member with a reviewer agent can approve or reject work.")
    if approval.status != "pending":
        raise ApiError(409, f"This approval was already {approval.status}.")

    output = db.get(Record, approval.record_id)
    task = db.get(Record, approval.task_id)
    if output.current_revision_id != approval.revision_id:
        raise ApiError(409, f"{ledger.label(output)} has a newer revision; this one can no longer be approved.")

    now = utcnow()
    approval.status = body.decision
    approval.decided_by_user_id = user.id
    approval.decided_at = now
    approval.comment = (body.comment or "").strip() or None
    rev = db.get(Revision, approval.revision_id)

    if body.decision == "approved":
        output.status = "approved"
        task.status = "approved"
    else:
        output.status = "rejected"
        task.status = "open"  # back on the board for an agent to redo
        for claim in db.execute(select(Claim).where(Claim.task_id == task.id, Claim.status == "active")).scalars():
            claim.status, claim.ended_at = "released", now

    actor = actor_user(user, member.role)
    verb = "approved" if body.decision == "approved" else "rejected"
    append_event(
        db, room.id, "approval.decided", actor,
        f"{user.display_name} {verb} {ledger.rev_label(output, rev.number)}"
        + (f": {approval.comment}" if approval.comment else ""),
        {"approval": approval_out(db, approval), "decided_by": actor},
        record_ids=[output.id, task.id],
    )
    db.commit()
    return {"approval": approval_out(db, approval), "record": record_out(db, output), "task": record_out(db, task)}
