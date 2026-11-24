"""Milestone 3: ledger, revisions, claims with leases, submissions and verification."""

import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.errors import AgentError
from app.models import Claim, Dependency, Record, Revision, Submission, utcnow
from app.services import claims as claim_svc
from app.services import submissions as sub_svc


def _ids(w):
    return [w.rev(w.brief), w.rev(w.dec1), w.rev(w.dec2), w.rev(w.dec3)]


def _submit(db, agent, w, key="k1", **kw):
    args = dict(
        task_ref="Task 1",
        content={"body": "## Launch plan\nLaunch on 10 January."},
        based_on=_ids(w),
        sources=[w.src1["record"]["id"]],
        idempotency_key=key,
    )
    args.update(kw)
    return sub_svc.submit(db, agent, **args)


# --- Ledger -----------------------------------------------------------------------------------


def test_records_get_labels_and_revision_1(world, client):
    r = client.get(f"/api/rooms/{world.room_id}/records?type=decision", headers=world.asha["h"]).json()["records"]
    assert [(x["label"], x["current_revision"], x["status"]) for x in r] == [
        ("Decision 1", 1, "approved"), ("Decision 2", 1, "approved"), ("Decision 3", 1, "approved"),
    ]
    assert world.task1["record"]["status"] == "open" and world.task1["record"]["label"] == "Task 1"


def test_editing_appends_a_revision_and_keeps_the_old_one(world, client, db):
    rid = world.dec2["record"]["id"]
    r = client.post(
        f"/api/records/{rid}/revisions",
        json={"content": {"statement": "We launch on 15 January."}, "note": "Exams moved."},
        headers=world.asha["h"],
    )
    assert r.status_code == 201, r.text
    assert r.json()["revision"]["number"] == 2
    detail = client.get(f"/api/records/{rid}", headers=world.asha["h"]).json()
    assert [v["number"] for v in detail["revisions"]] == [2, 1]
    assert detail["revisions"][1]["content"]["statement"] == "We launch on 10 January."
    assert detail["revisions"][0]["note"] == "Exams moved."
    v1 = client.get(f"/api/records/{rid}/revisions/1", headers=world.asha["h"]).json()
    assert v1["is_current"] is False
    count = db.execute(select(func.count()).select_from(Revision).where(Revision.record_id == uuid.UUID(rid))).scalar_one()
    assert count == 2
    types = [e["type"] for e in client.get(f"/api/rooms/{world.room_id}/events?record_id={rid}", headers=world.asha["h"]).json()["events"]]
    assert types == ["revision.created", "revision.created", "decision.changed"]


def test_only_mentors_write_records_and_content_is_validated(world, client):
    base = f"/api/rooms/{world.room_id}/records"
    r = client.post(base, json={"type": "decision", "title": "X", "content": {"statement": "y"}}, headers=world.ben["h"])
    assert r.status_code == 403
    r = client.post(base, json={"type": "decision", "title": "X", "content": {}}, headers=world.asha["h"])
    assert r.status_code == 422 and "statement" in r.json()["error"]["message"]
    r = client.post(base, json={"type": "task", "title": "X", "content": {"description": "d", "role": "boss"}}, headers=world.asha["h"])
    assert r.status_code == 422
    r = client.post(base, json={"type": "draft", "title": "X", "content": {"body": "b"}}, headers=world.asha["h"])
    assert r.status_code == 422  # drafts only come from agent submissions


def test_resolve_by_label(world, db):
    from app.services.ledger import resolve_record

    rec = resolve_record(db, uuid.UUID(world.room_id), "decision 2")
    assert rec.title == "Launch date"
    with pytest.raises(AgentError, match="not found"):
        resolve_record(db, uuid.UUID(world.room_id), "Decision 9")


# --- Claims -----------------------------------------------------------------------------------


def test_claim_is_exclusive_and_role_checked(world, db, agent_of, client):
    claude, codex = agent_of(world.claude), agent_of(world.codex)
    with pytest.raises(AgentError, match="needs a planner"):
        claim_svc.claim_task(db, codex, "Task 1")
    with pytest.raises(AgentError, match="no draft yet"):
        claim_svc.claim_task(db, codex, "Task 2")

    claim = claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    assert claim.status == "active"
    assert claim_svc.claim_task(db, claude, "Task 1").id == claim.id  # re-claim by holder is harmless

    other = client.post(f"/api/rooms/{world.room_id}/agents", json={"name": "Chen's Gemini", "tool": "gemini_cli", "role": "planner"}, headers=world.ben["h"]).json()
    with pytest.raises(AgentError, match="already claimed by Asha's Claude"):
        claim_svc.claim_task(db, agent_of(other), "Task 1")

    board = client.get(f"/api/rooms/{world.room_id}/board", headers=world.asha["h"]).json()["tasks"]
    assert board[0]["task"]["status"] == "claimed" and board[0]["claim"]["agent"]["name"] == "Asha's Claude"


def test_database_forbids_two_active_claims(world, db, agent_of):
    from sqlalchemy.exc import IntegrityError

    claude, codex = agent_of(world.claude), agent_of(world.codex)
    task_id = uuid.UUID(world.task1["record"]["id"])
    later = utcnow() + timedelta(minutes=5)
    db.add(Claim(task_id=task_id, agent_id=claude.id, status="active", lease_expires_at=later))
    db.add(Claim(task_id=task_id, agent_id=codex.id, status="active", lease_expires_at=later))
    with pytest.raises(IntegrityError):
        db.commit()


def test_parallel_claims_have_exactly_one_winner(world, client, database):
    from app.db import SessionLocal
    from app.models import Agent

    agents = []
    for i in range(6):
        body = client.post(f"/api/rooms/{world.room_id}/agents", json={"name": f"P{i}", "tool": "other", "role": "planner"}, headers=world.asha["h"]).json()
        agents.append(uuid.UUID(body["agent"]["id"]))
    wins, losses = [], []
    barrier = threading.Barrier(len(agents))

    def go(agent_id):
        barrier.wait()  # all start together; SQLite then lets exactly one BEGIN IMMEDIATE through at a time
        with SessionLocal() as s:
            agent = s.get(Agent, agent_id)
            try:
                claim_svc.claim_task(s, agent, "Task 1")
                s.commit()
                wins.append(agent_id)
            except AgentError:
                s.rollback()
                losses.append(agent_id)

    threads = [threading.Thread(target=go, args=(a,)) for a in agents]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(wins) == 1 and len(losses) == 5


def test_lease_expiry_frees_the_task(world, db, agent_of, client):
    claude = agent_of(world.claude)
    claim = claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    claim.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert claim_svc.expire_due(db) == 1
    db.commit()
    db.refresh(claim)
    assert claim.status == "expired"
    task = db.get(Record, uuid.UUID(world.task1["record"]["id"]))
    assert task.status == "open"
    events = client.get(f"/api/rooms/{world.room_id}/events?types=claim.expired", headers=world.asha["h"]).json()["events"]
    assert events[0]["actor"]["kind"] == "system"
    with pytest.raises(AgentError, match="not claimed"):
        claim_svc.heartbeat(db, claude, "Task 1")


def test_heartbeat_extends_and_release_reopens(world, db, agent_of):
    claude = agent_of(world.claude)
    claim = claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    first = claim.lease_expires_at
    claim.lease_expires_at = first - timedelta(minutes=10)
    db.commit()
    claim_svc.heartbeat(db, claude, "Task 1")
    db.commit()
    assert claim.lease_expires_at > first - timedelta(seconds=5)
    claim_svc.release_task(db, claude, "Task 1")
    db.commit()
    assert db.get(Record, claim.task_id).status == "open"


# --- Submissions & verification ----------------------------------------------------------------


def test_full_submit_creates_draft_revision(world, db, agent_of, client):
    claude = agent_of(world.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    out = _submit(db, claude, world)
    assert out["ok"] and out["status"] == "completed", out
    assert [c["name"] for c in out["checks"]] == ["claim_valid", "revisions_current", "content_schema"]
    assert all(c["passed"] for c in out["checks"])
    assert out["result"]["label"] == "Draft 1" and out["result"]["revision"] == 1
    assert out["result"]["status"] == "in_review"  # room requires approval by default

    draft = db.get(Record, uuid.UUID(out["result"]["record_id"]))
    assert draft.parent_task_id == uuid.UUID(world.task1["record"]["id"])
    rev = db.get(Revision, draft.current_revision_id)
    assert sorted(rev.based_on) == sorted(_ids(world))
    deps = db.execute(select(Dependency.kind, func.count()).where(Dependency.from_revision_id == rev.id).group_by(Dependency.kind)).all()
    assert dict(deps) == {"based_on": 4, "cites": 1}
    assert db.execute(select(Claim.status).where(Claim.task_id == draft.parent_task_id)).scalar_one() == "released"

    types = [e["type"] for e in client.get(f"/api/rooms/{world.room_id}/events?since_seq=0&limit=500", headers=world.asha["h"]).json()["events"]]
    tail = types[types.index("task.claimed"):]
    assert tail == ["task.claimed"] + ["verification.check"] * 3 + [
        "submission.saved", "revision.created", "submission.completed", "task.released", "approval.requested",
    ]
    board = client.get(f"/api/rooms/{world.room_id}/board", headers=world.asha["h"]).json()["tasks"]
    assert board[0]["output"]["label"] == "Draft 1" and board[0]["pending_approval"]["reason"] == "require_approval"


def test_submit_without_approval_is_approved(world, db, agent_of, client):
    client.patch(f"/api/rooms/{world.room_id}/settings", json={"require_approval": False}, headers=world.asha["h"])
    claude = agent_of(world.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    assert _submit(db, claude, world)["result"]["status"] == "approved"


def test_stale_based_on_is_rejected_with_actionable_message(world, db, agent_of, client):
    claude = agent_of(world.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    client.post(f"/api/records/{world.dec2['record']['id']}/revisions", json={"content": {"statement": "15 January."}}, headers=world.asha["h"])
    out = _submit(db, claude, world)
    assert out["ok"] is False and out["status"] == "rejected"
    assert out["checks"][-1]["name"] == "revisions_current"
    assert out["checks"][-1]["detail"].startswith("stale: based on Decision 2 v1, now v2")
    assert 'read_record("Decision 2")' in out["checks"][-1]["detail"]
    assert len(out["checks"]) == 2  # stops at the first failure
    assert db.execute(select(func.count()).select_from(Record).where(Record.type == "draft")).scalar_one() == 0


@pytest.mark.parametrize(
    "kw, check, text",
    [
        ({"based_on": []}, "revisions_current", "based_on is empty"),
        ({"based_on": [str(uuid.uuid4())]}, "revisions_current", "unknown revision"),
        ({"sources": ["Source 9"]}, "content_schema", "not found"),
        ({"sources": ["Decision 1"]}, "content_schema", "not a source"),
        ({"content": {"text": "no body"}}, "content_schema", "body"),
    ],
)
def test_each_check_rejects(world, db, agent_of, kw, check, text):
    claude = agent_of(world.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    out = _submit(db, claude, world, key=f"k-{check}-{text}", **kw)
    assert out["status"] == "rejected"
    assert out["checks"][-1]["name"] == check and text in out["checks"][-1]["detail"], out["checks"][-1]


def test_unclaimed_submit_fails_claim_valid(world, db, agent_of):
    out = _submit(db, agent_of(world.claude), world)
    assert out["checks"][0]["name"] == "claim_valid" and out["checks"][0]["detail"].startswith("not claimed")


def test_sources_are_optional(world, db, agent_of):
    claude = agent_of(world.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    out = _submit(db, claude, world, sources=[])
    assert out["status"] == "completed" and len(out["checks"]) == 3


def test_same_key_is_applied_once(world, db, agent_of):
    claude = agent_of(world.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    first = _submit(db, claude, world, key="once")
    again = _submit(db, claude, world, key="once")
    assert again["submission_id"] == first["submission_id"] and again["attempts"] == 2
    assert "Already applied" in again["message"]
    assert db.execute(select(func.count()).select_from(Revision).join(Record, Record.id == Revision.record_id).where(Record.type == "draft")).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(Submission)).scalar_one() == 1


def test_crash_after_save_then_retry_applies_once(world, db, agent_of):
    claude = agent_of(world.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    with pytest.raises(sub_svc.SimulatedCrash):
        _submit(db, claude, world, key="crashy", crash_after_save=True)
    sub = db.execute(select(Submission).where(Submission.idempotency_key == "crashy")).scalar_one()
    assert sub.status == "saved" and sub.result_revision_id is None
    out = _submit(db, claude, world, key="crashy")
    assert out["status"] == "completed" and out["resumed"] is True and out["attempts"] == 2
    _submit(db, claude, world, key="crashy")
    assert db.execute(select(func.count()).select_from(Revision).join(Record, Record.id == Revision.record_id).where(Record.type == "draft")).scalar_one() == 1


def test_review_handoff_needs_current_draft(world, db, agent_of, client):
    client.patch(f"/api/rooms/{world.room_id}/settings", json={"require_approval": False}, headers=world.asha["h"])
    claude, codex = agent_of(world.claude), agent_of(world.codex)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    draft = _submit(db, claude, world)["result"]

    claim_svc.claim_task(db, codex, "Task 2")
    db.commit()
    review = {"verdict": "approve", "comments": "Matches the brief and Decision 2."}
    out = sub_svc.submit(db, codex, "Task 2", review, _ids(world), [], "r1")
    assert out["status"] == "rejected" and "Draft 1 v1, the draft you are reviewing" in out["checks"][-1]["detail"]
    out = sub_svc.submit(db, codex, "Task 2", review, _ids(world) + [draft["revision_id"]], [], "r2")
    assert out["status"] == "completed" and out["result"]["label"] == "Review 2"
