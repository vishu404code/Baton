"""Records API (contract §6). Stale propagation and preview are completed in milestone 5."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.auth import current_user, get_membership, require_mentor
from app.db import get_db
from app.errors import ApiError, not_found
from app.models import Agent, Approval, Comment, Dependency, Record, Revision, Room, RoomMember, Submission, User
from app.record_views import (
    approval_out,
    comment_out,
    record_out,
    revision_out,
    revisions_of,
    submission_out,
)
from app.schemas import _In
from app.serializers import actor_user
from app.services import claims as claim_svc
from app.services import ledger, staleness
from app.services.events import append_event
from app.services.claims import claim_out

router = APIRouter(prefix="/api", tags=["records"])


class RecordCreateIn(_In):
    type: Literal["brief", "decision", "task", "source"]
    title: str = Field(min_length=1, max_length=200)
    content: dict


class RevisionIn(_In):
    content: dict
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class CommentIn(_In):
    text: str = Field(min_length=1, max_length=4000)


def record_access(db: Session, record_id: uuid.UUID, user: User) -> tuple[Record, Room, RoomMember]:
    record = db.get(Record, record_id)
    if record is None:
        raise not_found("Record not found.")
    room, member = get_membership(db, record.room_id, user)
    return record, room, member


def _validate(db: Session, room_id: uuid.UUID, type_: str, content: dict) -> None:
    problems = ledger.content_problems(type_, content)
    if type_ == "task" and content.get("review_of_task_id"):
        try:
            reviewed = db.get(Record, uuid.UUID(str(content["review_of_task_id"])))
        except ValueError:
            reviewed = None
        if reviewed is None or reviewed.room_id != room_id or reviewed.type != "task":
            problems.append("review_of_task_id must be a task in this room")
        if content.get("role") != "reviewer":
            problems.append("only reviewer tasks can have review_of_task_id")
    if problems:
        raise ApiError(422, f"{type_} content invalid: {'; '.join(problems)}.", details={"problems": problems})


@router.get("/rooms/{room_id}/records")
def list_records(
    room_id: uuid.UUID,
    type: str | None = None,
    status: str | None = None,
    parent_task_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_membership(db, room_id, user)
    stmt = select(Record).where(Record.room_id == room_id)
    if type:
        stmt = stmt.where(Record.type.in_(type.split(",")))
    if status:
        stmt = stmt.where(Record.status.in_(status.split(",")))
    if parent_task_id:
        stmt = stmt.where(Record.parent_task_id == parent_task_id)
    order = {t: i for i, t in enumerate(ledger.TYPE_LABEL)}
    rows = sorted(db.execute(stmt).scalars().all(), key=lambda r: (order[r.type], r.number))
    return {"records": [record_out(db, r) for r in rows]}


def board_item(db: Session, task: Record) -> dict:
    claim = claim_svc.active_claim(db, task)
    claim_json = None
    if claim:
        agent = db.get(Agent, claim.agent_id)
        claim_json = claim_out(claim, agent, db.get(User, agent.user_id).display_name)
    output = ledger.output_of(db, task)
    output_json = None
    stale_reason = None
    if output:
        rev = ledger.current_revision(db, output)
        out = revision_out(db, rev, output)
        output_json = {
            "record_id": str(output.id),
            "label": ledger.label(output),
            "type": output.type,
            "revision": output.current_revision,
            "revision_id": str(output.current_revision_id),
            "status": output.status,
            "author": out["author"],
        }
        if output.status == "stale":
            old = next((b for b in out["based_on"] if not b["is_current"]), None)
            if old:
                rec = db.get(Record, uuid.UUID(old["record_id"]))
                stale_reason = f"based on {old['label']} v{old['number']}, now v{rec.current_revision}"
    pending = db.execute(
        select(Approval).where(Approval.task_id == task.id, Approval.status == "pending").order_by(Approval.requested_at.desc())
    ).scalars().first()
    last = db.execute(
        select(Submission).where(Submission.task_id == task.id).order_by(Submission.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    return {
        "task": record_out(db, task),
        "claim": claim_json,
        "output": output_json,
        "stale_reason": stale_reason,
        "pending_approval": approval_out(db, pending) if pending else None,
        "last_submission": (
            {"id": str(last.id), "status": last.status, "created_at": submission_out(db, last)["created_at"]} if last else None
        ),
    }


@router.get("/rooms/{room_id}/board")
def board(room_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    get_membership(db, room_id, user)
    tasks = db.execute(
        select(Record).where(Record.room_id == room_id, Record.type == "task").order_by(Record.number)
    ).scalars().all()
    items = [board_item(db, t) for t in tasks]
    db.commit()  # persist any lease expiries noticed while reading
    return {"tasks": items, "columns": ["open", "claimed", "in_review", "stale", "approved", "rejected"]}


@router.get("/records/{record_id}")
def get_record(record_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    record, room, _ = record_access(db, record_id, user)
    body: dict = {"record": record_out(db, record), "revisions": revisions_of(db, record)}

    comments = db.execute(select(Comment).where(Comment.record_id == record.id).order_by(Comment.created_at)).scalars()
    body["comments"] = [comment_out(db, c, room.id) for c in comments]

    if record.type == "task":
        item = board_item(db, record)
        body["claim"] = item["claim"]
        output = ledger.output_of(db, record)
        body["outputs"] = [{"record": record_out(db, output), "revisions": revisions_of(db, output)}] if output else []
        subs = db.execute(
            select(Submission).where(Submission.task_id == record.id).order_by(Submission.created_at.desc())
        ).scalars()
        body["submissions"] = [submission_out(db, s) for s in subs]
        approvals = db.execute(
            select(Approval).where(Approval.task_id == record.id).order_by(Approval.requested_at.desc())
        ).scalars()
        body["approvals"] = [approval_out(db, a) for a in approvals]
        brief = ledger.latest(db, room.id, "brief")
        body["brief"] = record_out(db, brief) if brief else None
    body["dependents"] = dependents(db, record)
    db.commit()
    return body


def dependents(db: Session, record: Record) -> list[dict]:
    """Output records whose current revision is based on any revision of this record."""
    target = aliased(Revision)
    rows = db.execute(
        select(Record)
        .join(Revision, Revision.id == Record.current_revision_id)
        .join(Dependency, Dependency.from_revision_id == Revision.id)
        .join(target, target.id == Dependency.to_revision_id)
        .where(target.record_id == record.id)
        .distinct()
    ).scalars().all()
    return [
        {"record_id": str(r.id), "label": ledger.label(r), "type": r.type, "revision": r.current_revision, "status": r.status}
        for r in rows
        if r.id != record.id
    ]


@router.get("/records/{record_id}/revisions/{number}")
def get_revision(record_id: uuid.UUID, number: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    record, _, _ = record_access(db, record_id, user)
    rev = ledger.get_revision(db, record, number)
    if rev is None:
        raise not_found(f"{ledger.label(record)} has no revision {number}.")
    return revision_out(db, rev, record)


@router.post("/rooms/{room_id}/records", status_code=201)
def create_record(
    room_id: uuid.UUID, body: RecordCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    room, member = get_membership(db, room_id, user)
    require_mentor(member, f"create a {body.type}")
    _validate(db, room.id, body.type, body.content)
    record, rev = ledger.create_record(
        db, room.id, body.type, body.title, body.content, author_user_id=user.id,
        status="open" if body.type == "task" else "approved",
    )
    actor = actor_user(user, member.role)
    rec_out = record_out(db, record)
    append_event(
        db, room.id, "revision.created", actor,
        f"{user.display_name} created {ledger.label(record)} \"{record.title}\"",
        {"record": rec_out, "revision": revision_out(db, rev, record)}, record_ids=[record.id],
    )
    if body.type == "task":
        append_event(
            db, room.id, "task.created", actor,
            f"{user.display_name} created {ledger.label(record)} \"{record.title}\" for a {body.content.get('role')}",
            {"task": rec_out}, record_ids=[record.id],
        )
    db.commit()
    return {"record": record_out(db, record), "revision": revision_out(db, rev, record)}


@router.post("/records/{record_id}/revisions", status_code=201)
def add_revision(
    record_id: uuid.UUID, body: RevisionIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    record, room, member = record_access(db, record_id, user)
    require_mentor(member, f"edit {ledger.label(record)}")
    if record.type not in ledger.MENTOR_TYPES:
        raise ApiError(409, f"{ledger.label(record)} is agent output; agents change it by submitting through Baton.")
    _validate(db, room.id, record.type, body.content)
    db.execute(select(Record).where(Record.id == record.id).with_for_update())
    before = ledger.current_revision(db, record)
    rev = ledger.append_revision(db, record, body.content, title=body.title, author_user_id=user.id, note=body.note)
    actor = actor_user(user, member.role)
    append_event(
        db, room.id, "revision.created", actor,
        f"{user.display_name} updated {ledger.label(record)} to v{rev.number}",
        {"record": record_out(db, record), "revision": revision_out(db, rev, record)}, record_ids=[record.id],
    )
    stale: list[dict] = []
    unaffected: list[dict] = []
    if record.type in staleness.SOURCES_OF_TRUTH:
        will_go_stale = [a for a in staleness.find_affected(db, record) if a.record.status != "stale"]
        if record.type == "decision":
            append_event(
                db, room.id, "decision.changed", actor,
                f"{user.display_name} changed {ledger.label(record)} \"{record.title}\" to v{rev.number}"
                + (f"; {len(will_go_stale)} item{'s' if len(will_go_stale) != 1 else ''} will be marked stale" if will_go_stale else ""),
                {
                    "record": ledger.record_ref(record), "from_revision": before.number if before else 0,
                    "to_revision": rev.number, "before": before.content if before else None, "after": rev.content,
                    "note": body.note, "stale_count": len(will_go_stale),
                },
                record_ids=[record.id],
            )
        stale = staleness.propagate(db, record, before.number if before else 0, rev.number)
        affected_ids = {uuid.UUID(s["record_id"]) for s in stale}
        unaffected = [
            staleness.unaffected_out(db, r)
            for r in staleness.unaffected_outputs(db, room.id, [])
            if r.id not in affected_ids
        ]
    db.commit()
    return {"record": record_out(db, record), "revision": revision_out(db, rev, record), "stale": stale, "unaffected": unaffected}


@router.post("/records/{record_id}/revisions/preview")
def preview_revision(
    record_id: uuid.UUID, body: RevisionIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    """What WOULD go stale if this edit were saved. Writes nothing."""
    record, room, member = record_access(db, record_id, user)
    require_mentor(member, f"edit {ledger.label(record)}")
    if record.type not in ledger.MENTOR_TYPES:
        raise ApiError(409, f"{ledger.label(record)} is agent output; agents change it by submitting through Baton.")
    _validate(db, room.id, record.type, body.content)
    affected = []
    if record.type in staleness.SOURCES_OF_TRUTH:
        affected = [a for a in staleness.find_affected(db, record, preview=True) if a.record.status != "stale"]
    return {
        "would_go_stale": [staleness.affected_out(db, a) for a in affected],
        "unaffected": [staleness.unaffected_out(db, r) for r in staleness.unaffected_outputs(db, room.id, affected)],
        "next_revision": record.current_revision + 1,
    }


@router.post("/records/{record_id}/comments", status_code=201)
def add_comment(record_id: uuid.UUID, body: CommentIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    record, room, member = record_access(db, record_id, user)
    c = Comment(record_id=record.id, revision_number=record.current_revision, author_user_id=user.id, text=body.text)
    db.add(c)
    db.flush()
    out = comment_out(db, c, room.id)
    append_event(
        db, room.id, "comment.added", actor_user(user, member.role),
        f"{user.display_name} commented on {ledger.label(record)}",
        {"comment": out, "record": ledger.record_ref(record)}, record_ids=[record.id],
    )
    db.commit()
    return out


# --- Submissions (read-only over REST; agents submit via MCP) -------------------------------


@router.get("/rooms/{room_id}/submissions")
def list_submissions(
    room_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    status: str | None = None,
    agent_id: uuid.UUID | None = None,
    limit: int = 100,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_membership(db, room_id, user)
    stmt = select(Submission).where(Submission.room_id == room_id)
    if task_id:
        stmt = stmt.where(Submission.task_id == task_id)
    if status:
        stmt = stmt.where(Submission.status.in_(status.split(",")))
    if agent_id:
        stmt = stmt.where(Submission.agent_id == agent_id)
    rows = db.execute(stmt.order_by(Submission.created_at.desc()).limit(min(max(limit, 1), 500))).scalars()
    return {"submissions": [submission_out(db, s) for s in rows]}


@router.get("/submissions/{submission_id}")
def get_submission(submission_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    sub = db.get(Submission, submission_id)
    if sub is None:
        raise not_found("Submission not found.")
    get_membership(db, sub.room_id, user)
    return submission_out(db, sub)
