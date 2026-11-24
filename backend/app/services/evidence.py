"""Evidence views built from the ledger and the event log: recovery proof and the trace graph."""

from __future__ import annotations

import uuid
from collections import deque
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Agent, Approval, Dependency, Event, Record, Revision, RoomMember, Submission, User, utcnow
from app.record_views import author_actor
from app.services.events import iso
from app.services.ledger import label, output_of, rev_label

# A submission still `saved` this long after saving was interrupted (normal applies take ms).
INTERRUPTED_AFTER = timedelta(seconds=5)
RECOVERY_EVENT_TYPES = (
    "submission.saved", "agent.crashed", "submission.resumed", "revision.created",
    "submission.completed", "submission.duplicate",
)


# --- Recovery ---------------------------------------------------------------------------------


def _events_for_submission(db: Session, sub: Submission) -> list[Event]:
    sid = str(sub.id)
    p = Event.payload
    return list(
        db.execute(
            select(Event)
            .where(
                Event.room_id == sub.room_id,
                Event.type.in_(RECOVERY_EVENT_TYPES),
                or_(
                    p["submission_id"].as_string() == sid,
                    p["submission"]["id"].as_string() == sid,
                    p["revision"]["submission_id"].as_string() == sid,
                ),
            )
            .order_by(Event.seq)
        ).scalars()
    )


def recovery(db: Session, room_id: uuid.UUID) -> list[dict]:
    cutoff = utcnow() - INTERRUPTED_AFTER
    subs = db.execute(
        select(Submission)
        .where(
            Submission.room_id == room_id,
            or_(
                Submission.interrupted.is_(True),
                Submission.resumed.is_(True),
                Submission.attempts > 1,
                (Submission.status == "saved") & (Submission.saved_at < cutoff),
            ),
        )
        .order_by(Submission.created_at.desc())
    ).scalars().all()
    items = []
    for sub in subs:
        if sub.status == "rejected":
            continue  # a rejected key is just refused on retry; nothing to recover
        task = db.get(Record, sub.task_id)
        events = _events_for_submission(db, sub)
        resumed_at = next((e.created_at for e in events if e.type == "submission.resumed"), None)
        # Counted from the database, not assumed: revisions this key ever produced.
        revisions_for_key = db.execute(
            select(func.count())
            .select_from(Revision)
            .join(Submission, Submission.id == Revision.submission_id)
            .where(Submission.idempotency_key == sub.idempotency_key)
        ).scalar_one()
        result_revision = None
        if sub.result_revision_id:
            rev = db.get(Revision, sub.result_revision_id)
            rec = db.get(Record, rev.record_id)
            result_revision = {"id": str(rev.id), "record_id": str(rec.id), "label": label(rec), "number": rev.number}
        if sub.status == "saved":
            state = "interrupted"
        elif sub.resumed:
            state = "resumed"
        else:
            state = "duplicate_ignored"
        items.append(
            {
                "submission_id": str(sub.id),
                "idempotency_key": sub.idempotency_key,
                "task": {"id": str(task.id), "label": label(task), "title": task.title},
                "agent": author_actor(db, agent_id=sub.agent_id),
                "state": state,
                "status": sub.status,
                "attempts": sub.attempts,
                "saved_at": iso(sub.saved_at),
                "interrupted": bool(sub.interrupted or sub.status == "saved"),
                "resumed_at": iso(resumed_at),
                "completed_at": iso(sub.completed_at),
                "result_revision": result_revision,
                "applied_count": 1 if sub.status == "completed" else 0,
                "revisions_created_for_key": revisions_for_key,
                "timeline": [{"seq": e.seq, "type": e.type, "at": iso(e.created_at)} for e in events],
            }
        )
    return items


# --- Trace ------------------------------------------------------------------------------------

STORY_TYPES = ("revision.created", "decision.changed", "record.stale", "approval.decided", "task.claimed", "agent.crashed", "submission.resumed")


def trace(db: Session, record: Record, revision_number: int | None = None) -> dict:
    if record.type == "task":
        out = output_of(db, record)
        if out is None:
            return {"root": None, "nodes": [], "edges": [], "story": [], "message": f"{label(record)} has no output yet."}
        record = out
    if revision_number:
        root = db.execute(
            select(Revision).where(Revision.record_id == record.id, Revision.number == revision_number)
        ).scalar_one_or_none()
        if root is None:
            return {"root": None, "nodes": [], "edges": [], "story": [], "message": f"{label(record)} has no v{revision_number}."}
    else:
        root = db.get(Revision, record.current_revision_id)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    edge_keys: set[tuple] = set()

    def add_edge(frm: str, to: str, kind: str, at=None) -> None:
        key = (frm, to, kind)
        if key in edge_keys:
            return
        edge_keys.add(key)
        e = {"from": frm, "to": to, "kind": kind}
        if at is not None:
            e["at"] = iso(at)
        edges.append(e)

    def actor_node(actor: dict) -> str | None:
        if actor["kind"] == "agent":
            nid = f"agent:{actor['id']}"
            nodes.setdefault(nid, {"id": nid, "kind": "agent", "label": actor["name"], "tool": actor["tool"],
                                   "role": actor["role"], "color": actor["color"], "user_name": actor["user_name"]})
            return nid
        if actor["kind"] == "user":
            nid = f"user:{actor['id']}"
            nodes.setdefault(nid, {"id": nid, "kind": "user", "label": actor["name"], "room_role": actor.get("room_role")})
            return nid
        return None

    def rev_node(rev: Revision, rec: Record) -> str:
        nid = f"rev:{rev.id}"
        if nid not in nodes:
            is_current = rec.current_revision_id == rev.id
            nodes[nid] = {
                "id": nid, "kind": "revision", "revision_id": str(rev.id), "record_id": str(rec.id),
                "record_type": rec.type, "label": rev_label(rec, rev.number), "title": rev.title,
                "status": rec.status if is_current else "superseded",
                "is_current": is_current, "created_at": iso(rev.created_at),
            }
        return nid

    queue: deque[Revision] = deque([root])
    visited: set[uuid.UUID] = set()
    while queue and len(visited) < 200:
        rev = queue.popleft()
        if rev.id in visited:
            continue
        visited.add(rev.id)
        rec = db.get(Record, rev.record_id)
        nid = rev_node(rev, rec)

        author = author_actor(db, agent_id=rev.author_agent_id, user_id=rev.author_user_id, room_id=rec.room_id)
        a = actor_node(author)
        if a:
            add_edge(nid, a, "authored_by", rev.created_at)

        for dep in db.execute(select(Dependency).where(Dependency.from_revision_id == rev.id)).scalars():
            target = db.get(Revision, dep.to_revision_id)
            trec = db.get(Record, target.record_id)
            add_edge(nid, rev_node(target, trec), "cites" if dep.kind == "cites" else "based_on")
            queue.append(target)

        # Older versions of the same record: the correction history.
        prev = db.execute(
            select(Revision).where(Revision.record_id == rec.id, Revision.number == rev.number - 1)
        ).scalar_one_or_none()
        if prev is not None:
            add_edge(nid, rev_node(prev, rec), "supersedes")
            queue.append(prev)
        # Newer versions of inputs (e.g. Decision 2 v2 when the draft used v1) explain the staleness.
        if rec.type in ("decision", "brief", "source") and rec.current_revision_id != rev.id:
            cur = db.get(Revision, rec.current_revision_id)
            add_edge(rev_node(cur, rec), nid, "supersedes")
            queue.append(cur)

        for appr in db.execute(select(Approval).where(Approval.revision_id == rev.id, Approval.decided_by_user_id.is_not(None))).scalars():
            u = actor_node(author_actor(db, user_id=appr.decided_by_user_id, room_id=rec.room_id))
            add_edge(nid, u, "approved_by" if appr.status == "approved" else "rejected_by", appr.decided_at)

    # Agents belong to people: link them so the trace reaches the teammate behind each agent.
    for n in list(nodes.values()):
        if n["kind"] == "agent":
            agent = db.get(Agent, uuid.UUID(n["id"].split(":", 1)[1]))
            owner = db.get(User, agent.user_id)
            m = db.get(RoomMember, (agent.room_id, owner.id))
            u = actor_node({"kind": "user", "id": str(owner.id), "name": owner.display_name, "room_role": m.role if m else None})
            add_edge(n["id"], u, "owned_by")

    record_ids = sorted({n["record_id"] for n in nodes.values() if n["kind"] == "revision"})
    if record.parent_task_id:
        record_ids.append(str(record.parent_task_id))
    story = []
    if record_ids:
        wanted = set(record_ids)
        events = (
            e
            for e in db.execute(
                select(Event).where(Event.room_id == record.room_id, Event.type.in_(STORY_TYPES)).order_by(Event.seq)
            ).scalars()
            if wanted & set(e.record_ids or [])
        )
        for e in events:
            if e.type == "revision.created" and e.payload.get("revision", {}).get("number", 1) > 1 and (e.payload.get("record") or {}).get("type") == "decision":
                continue  # decision.changed tells this better
            if e.type == "task.claimed" and str(record.parent_task_id) not in (e.record_ids or []):
                continue
            story.append({"seq": e.seq, "at": iso(e.created_at), "type": e.type, "text": e.summary})

    return {"root": f"rev:{root.id}", "record": {"id": str(record.id), "label": label(record), "title": record.title},
            "nodes": list(nodes.values()), "edges": edges, "story": story}
