"""Milestone 5: stale propagation, edit preview, approvals, and redo of stale work (test 4)."""

import uuid

import pytest
from sqlalchemy import func, select

from app.models import Approval, Claim, Event, Record, Revision
from app.services import claims as claim_svc
from app.services import submissions as sub_svc


@pytest.fixture()
def done(world, client, db, agent_of):
    """Draft 1 (Task 1, uses Decision 2), Review 1 (Task 2, reviews Draft 1) and an independent
    Draft 2 (Task 3, uses only the brief and Decision 3), all approved."""
    w = world
    w.task3 = w.create("task", "Draft volunteer rota", {"description": "Rota.", "role": "planner"})
    claude, codex = agent_of(w.claude), agent_of(w.codex)
    base = [w.rev(w.brief), w.rev(w.dec1), w.rev(w.dec2), w.rev(w.dec3)]
    src = [w.src1["record"]["id"]]

    def run(agent, task, content, based_on, sources, key):
        claim_svc.claim_task(db, agent, task)
        db.commit()
        out = sub_svc.submit(db, agent, task, content, based_on, sources, key)
        assert out["status"] == "completed", out
        return out["result"]

    w.draft = run(claude, "Task 1", {"body": "Launch 10 January."}, base, src, "d1")
    # The review depends on Decision 2 only through Draft 1, to exercise transitive staleness.
    w.review = run(codex, "Task 2", {"verdict": "approve", "comments": "Good."}, [w.rev(w.brief), w.draft["revision_id"]], [], "r1")
    w.rota = run(claude, "Task 3", {"body": "12 volunteers."}, [w.rev(w.brief), w.rev(w.dec3)], [w.src2["record"]["id"]], "t3")
    for a in client.get(f"/api/rooms/{w.room_id}/approvals", headers=w.asha["h"]).json()["approvals"]:
        r = client.post(f"/api/approvals/{a['id']}/decide", json={"decision": "approved"}, headers=w.asha["h"])
        assert r.status_code == 200, r.text
    return w


def _status(db, record_id):
    db.expire_all()
    return db.get(Record, uuid.UUID(record_id)).status


def _edit_dec2(w, client, statement="We launch on 15 January."):
    return client.post(
        f"/api/records/{w.dec2['record']['id']}/revisions",
        json={"content": {"statement": statement, "rationale": "Exams end 12 January."}, "note": "Exams clash."},
        headers=w.asha["h"],
    )


def test_preview_lists_direct_and_transitive_and_writes_nothing(done, client, db):
    w = done
    before = (db.execute(select(func.count()).select_from(Revision)).scalar_one(),
              db.execute(select(func.count()).select_from(Event)).scalar_one())
    r = client.post(
        f"/api/records/{w.dec2['record']['id']}/revisions/preview",
        json={"content": {"statement": "We launch on 15 January."}}, headers=w.asha["h"],
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["next_revision"] == 2
    stale = {s["label"]: s for s in p["would_go_stale"]}
    assert set(stale) == {"Draft 1", "Review 2"}
    assert stale["Draft 1"]["reason"] == "based on Decision 2 v1, now v2"
    assert stale["Draft 1"]["path"] == ["Decision 2 v1", "Draft 1 v1"]
    assert stale["Review 2"]["path"] == ["Decision 2 v1", "Draft 1 v1", "Review 2 v1"]
    assert stale["Review 2"]["task_label"] == "Task 2"
    assert [u["label"] for u in p["unaffected"]] == ["Draft 3"]
    after = (db.execute(select(func.count()).select_from(Revision)).scalar_one(),
             db.execute(select(func.count()).select_from(Event)).scalar_one())
    assert before == after
    assert _status(db, w.draft["record_id"]) == "approved"


def test_changing_a_decision_marks_dependents_stale_and_keeps_independent_work(done, client, db):
    w = done
    r = _edit_dec2(w, client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["revision"]["number"] == 2
    assert {s["label"] for s in body["stale"]} == {"Draft 1", "Review 2"}
    assert [u["label"] for u in body["unaffected"]] == ["Draft 3"]

    assert _status(db, w.draft["record_id"]) == "stale"
    assert _status(db, w.review["record_id"]) == "stale"
    assert _status(db, w.task1["record"]["id"]) == "stale"
    assert _status(db, w.task2["record"]["id"]) == "stale"
    assert _status(db, w.rota["record_id"]) == "approved"
    assert _status(db, w.task3["record"]["id"]) == "approved"

    events = client.get(f"/api/rooms/{w.room_id}/events?types=decision.changed,record.stale", headers=w.asha["h"]).json()["events"]
    assert [e["type"] for e in events] == ["decision.changed", "record.stale", "record.stale"]
    assert events[0]["payload"]["stale_count"] == 2 and events[0]["payload"]["note"] == "Exams clash."
    review_ev = next(e for e in events if e["payload"].get("record", {}).get("label") == "Review 2")
    assert review_ev["payload"]["reason"] == "based on Draft 1 v1, which is stale (Decision 2 v1, now v2)"
    assert review_ev["payload"]["caused_by"]["to_revision"] == 2

    board = {t["task"]["label"]: t for t in client.get(f"/api/rooms/{w.room_id}/board", headers=w.asha["h"]).json()["tasks"]}
    assert board["Task 1"]["stale_reason"] == "based on Decision 2 v1, now v2"
    # A second edit doesn't re-flag what is already stale.
    r2 = _edit_dec2(w, client, "We launch on 16 January.")
    assert r2.json()["stale"] == []


def test_unrelated_decision_only_affects_its_own_dependents(done, client, db):
    w = done
    r = client.post(f"/api/records/{w.dec3['record']['id']}/revisions", json={"content": {"statement": "10 volunteers."}}, headers=w.asha["h"])
    labels = {s["label"] for s in r.json()["stale"]}
    assert labels == {"Draft 1", "Review 2", "Draft 3"}  # Draft 1 and the rota used Decision 3; the review via Draft 1


def test_editing_a_cited_source_flags_drafts_that_cite_it(done, client, db):
    w = done
    r = client.post(f"/api/records/{w.src2['record']['id']}/revisions", json={"content": {"text": "70% of students."}}, headers=w.asha["h"])
    assert [s["label"] for s in r.json()["stale"]] == ["Draft 3"]


def test_pending_approval_closes_when_work_goes_stale(world, client, db, agent_of):
    w = world
    claude = agent_of(w.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    out = sub_svc.submit(db, claude, "Task 1", {"body": "x"}, [w.rev(w.brief), w.rev(w.dec2)], [w.src1["record"]["id"]], "p1")
    assert out["result"]["status"] == "in_review"
    _edit_dec2(w, client)
    db.expire_all()
    a = db.execute(select(Approval)).scalar_one()
    assert a.status == "rejected" and a.comment.startswith("Closed automatically: based on Decision 2 v1")
    assert client.get(f"/api/rooms/{w.room_id}/approvals", headers=w.asha["h"]).json()["approvals"] == []


def test_redo_of_stale_work_needs_approval_then_traces_to_new_decision(done, client, db, agent_of):
    w = done
    client.patch(f"/api/rooms/{w.room_id}/settings", json={"require_approval": False}, headers=w.asha["h"])
    _edit_dec2(w, client)
    claude = agent_of(w.claude)

    # Resubmitting on the old decision is rejected as stale.
    claim = claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    assert claim.is_redo is True
    old = [w.rev(w.brief), w.rev(w.dec1), w.rev(w.dec2), w.rev(w.dec3)]
    out = sub_svc.submit(db, claude, "Task 1", {"body": "Launch 10 Jan."}, old, [w.src1["record"]["id"]], "redo-1")
    assert out["status"] == "rejected" and out["message"].startswith("Rejected by revisions_current: stale: based on Decision 2 v1, now v2")

    dec2_v2 = client.get(f"/api/records/{w.dec2['record']['id']}", headers=w.asha["h"]).json()["record"]["current_revision_id"]
    new = [w.rev(w.brief), w.rev(w.dec1), dec2_v2, w.rev(w.dec3)]
    out = sub_svc.submit(db, claude, "Task 1", {"body": "Launch 15 January."}, new, [w.src1["record"]["id"]], "redo-2")
    assert out["status"] == "completed", out
    assert out["result"]["label"] == "Draft 1" and out["result"]["revision"] == 2
    assert out["result"]["status"] == "in_review"  # redo of stale work always needs approval

    pending = client.get(f"/api/rooms/{w.room_id}/approvals", headers=w.asha["h"]).json()["approvals"]
    assert len(pending) == 1 and pending[0]["reason"] == "redo_of_stale"
    assert pending[0]["revision"]["content"]["body"] == "Launch 15 January."
    assert pending[0]["previous_revision"]["number"] == 1
    assert [b["label"] for b in pending[0]["revision"]["based_on"] if b["label"] == "Decision 2"] == ["Decision 2"]
    assert all(b["is_current"] for b in pending[0]["revision"]["based_on"])
    assert any(not b["is_current"] for b in pending[0]["previous_revision"]["based_on"])

    r = client.post(f"/api/approvals/{pending[0]['id']}/decide", json={"decision": "approved", "comment": "Dates match Decision 2 v2."}, headers=w.ben["h"])
    assert r.status_code == 200, r.text
    assert r.json()["record"]["status"] == "approved" and r.json()["task"]["status"] == "approved"
    assert _status(db, w.rota["record_id"]) == "approved"  # independent work preserved throughout


def test_approval_permissions_and_rules(done, client, api, db, agent_of):
    w = done
    chen = api.signup("Chen")
    api.join(chen, w.room["invite_code"])
    _edit_dec2(w, client)
    claude = agent_of(w.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    dec2_v2 = client.get(f"/api/records/{w.dec2['record']['id']}", headers=w.asha["h"]).json()["record"]["current_revision_id"]
    sub_svc.submit(db, claude, "Task 1", {"body": "15 Jan"}, [w.rev(w.brief), dec2_v2], [w.src1["record"]["id"]], "redo")
    a = client.get(f"/api/rooms/{w.room_id}/approvals", headers=w.asha["h"]).json()["approvals"][0]
    url = f"/api/approvals/{a['id']}/decide"

    r = client.post(url, json={"decision": "approved"}, headers=chen["h"])
    assert r.status_code == 403  # plain member without a reviewer agent
    r = client.post(url, json={"decision": "rejected"}, headers=w.ben["h"])
    assert r.status_code == 422 and "comment is required" in r.json()["error"]["message"]
    r = client.post(url, json={"decision": "rejected", "comment": "Missing the venue."}, headers=w.ben["h"])
    assert r.status_code == 200
    assert r.json()["record"]["status"] == "rejected" and r.json()["task"]["status"] == "open"
    assert client.post(url, json={"decision": "approved"}, headers=w.asha["h"]).status_code == 409
    ev = client.get(f"/api/rooms/{w.room_id}/events?types=approval.decided", headers=w.asha["h"]).json()["events"][-1]
    assert ev["summary"] == "Ben rejected Draft 1 v2: Missing the venue."


def test_holder_keeps_claim_when_decision_changes_mid_work(world, client, db, agent_of):
    w = world
    claude = agent_of(w.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    out = sub_svc.submit(db, claude, "Task 1", {"body": "v1"}, [w.rev(w.brief), w.rev(w.dec2)], [w.src1["record"]["id"]], "a")
    approval = client.get(f"/api/rooms/{w.room_id}/approvals", headers=w.asha["h"]).json()["approvals"][0]
    client.post(f"/api/approvals/{approval['id']}/decide", json={"decision": "rejected", "comment": "redo"}, headers=w.asha["h"])
    claim_svc.claim_task(db, claude, "Task 1")  # working on the redo...
    db.commit()
    _edit_dec2(w, client)  # ...when the decision changes. The draft was rejected, not stale, so nothing to flag.
    db.expire_all()
    c = db.execute(select(Claim).where(Claim.status == "active")).scalar_one()
    assert c.agent_id == claude.id
