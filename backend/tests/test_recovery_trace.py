"""Milestone 6: crash recovery evidence (test 5) and the trace graph (test 6)."""

import pytest

from app.services import claims as claim_svc
from app.services import submissions as sub_svc


def _base(w):
    return [w.rev(w.brief), w.rev(w.dec1), w.rev(w.dec2), w.rev(w.dec3)]


def _crash(world, db, claude, key="crash-1"):
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    with pytest.raises(sub_svc.SimulatedCrash):
        sub_svc.submit(db, claude, "Task 1", {"body": "Plan"}, _base(world), [world.src1["record"]["id"]], key, crash_after_save=True)
    sub_svc.record_crash(db, claude, key)


def test_recovery_shows_interrupted_then_resumed_applied_once(world, client, db, agent_of):
    claude = agent_of(world.claude)
    _crash(world, db, claude)
    url = f"/api/rooms/{world.room_id}/recovery"

    items = client.get(url, headers=world.asha["h"]).json()["items"]
    assert len(items) == 1
    it = items[0]
    assert it["state"] == "interrupted" and it["interrupted"] is True
    assert it["applied_count"] == 0 and it["revisions_created_for_key"] == 0
    assert [t["type"] for t in it["timeline"]] == ["submission.saved", "agent.crashed"]

    out = sub_svc.submit(db, claude, "Task 1", {"body": "Plan"}, _base(world), [world.src1["record"]["id"]], "crash-1")
    assert out["resumed"] is True
    sub_svc.submit(db, claude, "Task 1", {"body": "Plan"}, _base(world), [], "crash-1")  # duplicate

    it = client.get(url, headers=world.asha["h"]).json()["items"][0]
    assert it["state"] == "resumed" and it["attempts"] == 3
    assert it["applied_count"] == 1 and it["revisions_created_for_key"] == 1
    assert it["result_revision"]["label"] == "Draft 1" and it["resumed_at"] and it["completed_at"]
    assert [t["type"] for t in it["timeline"]] == [
        "submission.saved", "agent.crashed", "submission.resumed", "revision.created", "submission.completed", "submission.duplicate",
    ]


def test_normal_submissions_are_not_in_recovery(world, client, db, agent_of):
    claude = agent_of(world.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    sub_svc.submit(db, claude, "Task 1", {"body": "Plan"}, _base(world), [world.src1["record"]["id"]], "ok-1")
    assert client.get(f"/api/rooms/{world.room_id}/recovery", headers=world.asha["h"]).json()["items"] == []


def test_resume_after_decision_changed_applies_once_but_flags_stale(world, client, db, agent_of):
    claude = agent_of(world.claude)
    _crash(world, db, claude, "late-1")
    client.post(f"/api/records/{world.dec2['record']['id']}/revisions", json={"content": {"statement": "15 January."}}, headers=world.asha["h"])
    out = sub_svc.submit(db, claude, "Task 1", {"body": "Plan"}, _base(world), [], "late-1")
    assert out["status"] == "completed" and out["resumed"] is True
    assert out["result"]["status"] == "stale"
    ev = client.get(f"/api/rooms/{world.room_id}/events?types=record.stale", headers=world.asha["h"]).json()["events"]
    assert ev[-1]["summary"] == "Draft 1 v1 marked stale on arrival (based on Decision 2 v1, now v2)"
    assert client.get(f"/api/rooms/{world.room_id}/approvals", headers=world.asha["h"]).json()["approvals"] == []


def test_trace_from_corrected_output_back_to_the_decision_and_teammate(world, client, db, agent_of):
    """Draft 1 v1 used Decision 2 v1; Asha changes it to v2; Claude redoes the draft; Ben approves."""
    w = world
    claude = agent_of(w.claude)
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    sub_svc.submit(db, claude, "Task 1", {"body": "10 Jan"}, _base(w), [w.src1["record"]["id"]], "v1")
    first = client.get(f"/api/rooms/{w.room_id}/approvals", headers=w.asha["h"]).json()["approvals"][0]
    client.post(f"/api/approvals/{first['id']}/decide", json={"decision": "approved"}, headers=w.asha["h"])

    client.post(f"/api/records/{w.dec2['record']['id']}/revisions", json={"content": {"statement": "We launch on 15 January."}}, headers=w.asha["h"])
    dec2_v2 = client.get(f"/api/records/{w.dec2['record']['id']}", headers=w.asha["h"]).json()["record"]["current_revision_id"]
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    sub_svc.submit(db, claude, "Task 1", {"body": "15 Jan"}, [w.rev(w.brief), w.rev(w.dec1), dec2_v2, w.rev(w.dec3)], [w.src1["record"]["id"]], "v2")
    redo = client.get(f"/api/rooms/{w.room_id}/approvals", headers=w.asha["h"]).json()["approvals"][0]
    client.post(f"/api/approvals/{redo['id']}/decide", json={"decision": "approved", "comment": "Matches v2."}, headers=w.ben["h"])

    # Tracing the task uses its output.
    t = client.get(f"/api/records/{w.task1['record']['id']}/trace", headers=w.asha["h"]).json()
    nodes = {n["id"]: n for n in t["nodes"]}
    by_label = {n["label"]: n for n in t["nodes"]}
    edges = {(nodes[e["from"]]["label"], nodes[e["to"]]["label"], e["kind"]) for e in t["edges"]}

    assert nodes[t["root"]]["label"] == "Draft 1 v2" and nodes[t["root"]]["status"] == "approved"
    assert ("Draft 1 v2", "Decision 2 v2", "based_on") in edges
    assert ("Draft 1 v2", "Source 1 v1", "cites") in edges
    assert ("Draft 1 v2", "Draft 1 v1", "supersedes") in edges
    assert ("Draft 1 v1", "Decision 2 v1", "based_on") in edges
    assert ("Decision 2 v2", "Decision 2 v1", "supersedes") in edges
    assert ("Decision 2 v2", "Asha", "authored_by") in edges  # the teammate's decision
    assert ("Draft 1 v2", "Asha's Claude", "authored_by") in edges
    assert ("Asha's Claude", "Asha", "owned_by") in edges
    assert ("Draft 1 v2", "Ben", "approved_by") in edges
    assert by_label["Decision 2 v1"]["is_current"] is False and by_label["Decision 2 v1"]["status"] == "superseded"
    assert by_label["Asha's Claude"]["tool"] == "claude_code"

    story = [s["text"] for s in t["story"]]
    joined = "\n".join(story)
    assert "Asha changed Decision 2 \"Launch date\" to v2" in joined
    assert "Draft 1 v1 marked stale (based on Decision 2 v1, now v2)" in joined
    assert "Asha's Claude wrote Draft 1 v2 for Task 1" in joined
    assert "Ben approved Draft 1 v2: Matches v2." in joined
    assert [s["seq"] for s in t["story"]] == sorted(s["seq"] for s in t["story"])

    # An older revision can be traced too.
    old = client.get(f"/api/records/{by_label['Draft 1 v2']['record_id']}/trace?revision=1", headers=w.asha["h"]).json()
    assert {n["label"] for n in old["nodes"]} >= {"Draft 1 v1", "Decision 2 v1"}


def test_trace_of_task_without_output(world, client):
    t = client.get(f"/api/records/{world.task1['record']['id']}/trace", headers=world.asha["h"]).json()
    assert t["root"] is None and "no output yet" in t["message"]
