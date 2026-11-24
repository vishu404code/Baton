"""JSON shapes for records, revisions, submissions, approvals and comments (API contract §1.6–1.11)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Approval, Comment, Record, Revision, RoomMember, Submission, User, VerificationResult
from app.serializers import actor_agent, actor_user
from app.services.events import SYSTEM_ACTOR, iso
from app.services.ledger import label, rev_label


def author_actor(db: Session, *, agent_id=None, user_id=None, room_id=None) -> dict:
    if agent_id:
        agent = db.get(Agent, agent_id)
        return actor_agent(agent, db.get(User, agent.user_id).display_name)
    if user_id:
        user = db.get(User, user_id)
        role = None
        if room_id:
            m = db.get(RoomMember, (room_id, user_id))
            role = m.role if m else None
        return actor_user(user, role)
    return SYSTEM_ACTOR


def record_out(db: Session, record: Record, *, with_content: bool = True) -> dict:
    rev = db.get(Revision, record.current_revision_id) if record.current_revision_id else None
    out = {
        "id": str(record.id),
        "room_id": str(record.room_id),
        "type": record.type,
        "number": record.number,
        "label": label(record),
        "title": record.title,
        "status": record.status,
        "current_revision": record.current_revision,
        "current_revision_id": str(record.current_revision_id) if record.current_revision_id else None,
        "parent_task_id": str(record.parent_task_id) if record.parent_task_id else None,
        "updated_at": iso(record.updated_at),
        "updated_by": author_actor(
            db,
            agent_id=rev.author_agent_id if rev else None,
            user_id=rev.author_user_id if rev else None,
            room_id=record.room_id,
        ),
        "created_at": iso(record.created_at),
    }
    if with_content:
        out["content"] = rev.content if rev else {}
    return out


def based_on_out(db: Session, revision_ids: list[str]) -> list[dict]:
    items = []
    for rid in revision_ids:
        rev = db.get(Revision, uuid.UUID(str(rid)))
        if rev is None:
            continue
        rec = db.get(Record, rev.record_id)
        items.append(
            {
                "revision_id": str(rev.id),
                "record_id": str(rec.id),
                "type": rec.type,
                "label": label(rec),
                "number": rev.number,
                "is_current": rec.current_revision_id == rev.id,
            }
        )
    return items


def sources_out(db: Session, source_ids: list[str]) -> list[dict]:
    items = []
    for sid in source_ids:
        rec = db.get(Record, uuid.UUID(str(sid)))
        if rec is None:
            continue
        rev = db.get(Revision, rec.current_revision_id) if rec.current_revision_id else None
        content = rev.content if rev else {}
        items.append(
            {
                "record_id": str(rec.id),
                "label": label(rec),
                "title": rec.title,
                "revision_id": str(rec.current_revision_id) if rec.current_revision_id else None,
                "url": content.get("url"),
                "text": content.get("text"),
                "summary": content.get("summary"),
            }
        )
    return items


def revision_out(db: Session, rev: Revision, record: Record | None = None) -> dict:
    record = record or db.get(Record, rev.record_id)
    return {
        "id": str(rev.id),
        "record_id": str(rev.record_id),
        "label": rev_label(record, rev.number),
        "number": rev.number,
        "title": rev.title,
        "content": rev.content,
        "author": author_actor(db, agent_id=rev.author_agent_id, user_id=rev.author_user_id, room_id=record.room_id),
        "based_on": based_on_out(db, rev.based_on or []),
        "sources": sources_out(db, rev.source_ids or []),
        "note": rev.note,
        "submission_id": str(rev.submission_id) if rev.submission_id else None,
        "is_current": record.current_revision_id == rev.id,
        "created_at": iso(rev.created_at),
    }


def revisions_of(db: Session, record: Record) -> list[dict]:
    revs = db.execute(
        select(Revision).where(Revision.record_id == record.id).order_by(Revision.number.desc())
    ).scalars().all()
    return [revision_out(db, r, record) for r in revs]


def checks_out(db: Session, submission_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(VerificationResult)
        .where(VerificationResult.submission_id == submission_id)
        .order_by(VerificationResult.order)
    ).scalars().all()
    out = []
    for r in rows:
        item = {"name": r.check_name, "order": r.order, "passed": r.passed, "detail": r.detail}
        if r.skipped:
            item["skipped"] = True
        out.append(item)
    return out


def approval_out(db: Session, a: Approval) -> dict:
    record = db.get(Record, a.record_id)
    task = db.get(Record, a.task_id)
    decided_by = None
    if a.decided_by_user_id:
        decided_by = author_actor(db, user_id=a.decided_by_user_id, room_id=a.room_id)
    return {
        "id": str(a.id),
        "revision_id": str(a.revision_id),
        "record_id": str(a.record_id),
        "record_label": label(record),
        "task_id": str(a.task_id),
        "task_label": label(task),
        "reason": a.reason,
        "status": a.status,
        "requested_at": iso(a.requested_at),
        "decided_by": decided_by,
        "decided_at": iso(a.decided_at),
        "comment": a.comment,
    }


def submission_out(db: Session, sub: Submission) -> dict:
    task = db.get(Record, sub.task_id)
    approval = None
    if sub.result_revision_id:
        a = db.execute(select(Approval).where(Approval.revision_id == sub.result_revision_id)).scalar_one_or_none()
        if a:
            approval = {"id": str(a.id), "status": a.status}
    result_record_id = None
    if sub.result_revision_id:
        rr = db.get(Revision, sub.result_revision_id)
        result_record_id = str(rr.record_id) if rr else None
    return {
        "id": str(sub.id),
        "idempotency_key": sub.idempotency_key,
        "task_id": str(sub.task_id),
        "task_label": label(task),
        "agent": author_actor(db, agent_id=sub.agent_id),
        "status": sub.status,
        "base_revision_id": str(sub.base_revision_id) if sub.base_revision_id else None,
        "based_on": sub.based_on,
        "source_ids": sub.source_ids,
        "payload": {"title": sub.payload.get("title"), "content": sub.payload.get("content")},
        "checks": checks_out(db, sub.id),
        "rejection_reason": sub.rejection_reason,
        "result_revision_id": str(sub.result_revision_id) if sub.result_revision_id else None,
        "result_record_id": result_record_id,
        "attempts": sub.attempts,
        "resumed": sub.resumed,
        "approval": approval,
        "created_at": iso(sub.created_at),
        "saved_at": iso(sub.saved_at),
        "completed_at": iso(sub.completed_at),
    }


def comment_out(db: Session, c: Comment, room_id) -> dict:
    return {
        "id": str(c.id),
        "record_id": str(c.record_id),
        "revision_number": c.revision_number,
        "author": author_actor(db, agent_id=c.author_agent_id, user_id=c.author_user_id, room_id=room_id),
        "text": c.text,
        "created_at": iso(c.created_at),
    }
