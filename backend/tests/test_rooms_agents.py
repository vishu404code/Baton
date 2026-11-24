"""Milestone 2: sessions, rooms, invite codes, members, agents, tokens, config snippets, events."""

import re
import threading
import uuid

from app.config import get_settings

MCP_URL = get_settings().mcp_url  # follows BATON_PUBLIC_URL (LAN IP when set)

from sqlalchemy import select


# --- Sessions ---------------------------------------------------------------------------


def test_session_and_me(api, client):
    asha = api.signup("Asha")
    assert asha["token"].startswith("bs_")
    r = client.get("/api/me", headers=asha["h"])
    assert r.status_code == 200
    assert r.json()["user"]["display_name"] == "Asha"


def test_bad_token_uses_error_shape(client):
    r = client.get("/api/me", headers={"Authorization": "Bearer bs_nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert client.get("/api/me").status_code == 401


def test_validation_error_shape(client):
    r = client.post("/api/session", json={"display_name": ""})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert err["details"]["fields"][0]["loc"][-1] == "display_name"


def test_only_token_hashes_are_stored(api, db):
    from app.auth import hash_token
    from app.models import UserSession

    asha = api.signup("Asha")
    stored = db.execute(select(UserSession.token_hash)).scalars().all()
    assert stored == [hash_token(asha["token"])]
    assert asha["token"] not in stored


# --- Rooms ------------------------------------------------------------------------------


def test_create_room_makes_owner_and_invite_code(api):
    asha = api.signup("Asha")
    room = api.room(asha)
    assert room["my_role"] == "owner"
    assert re.fullmatch(r"CAMPUS-[A-Z2-9]{4}", room["invite_code"])
    assert room["settings"] == {
        "lease_minutes": 15,
        "require_approval": True,
    }
    assert room["counts"]["members"] == 1
    assert room["latest_seq"] == 1


def test_join_by_code_is_case_insensitive_and_idempotent(api, client):
    asha, ben = api.signup("Asha"), api.signup("Ben")
    room = api.room(asha)
    joined = api.join(ben, room["invite_code"].lower())
    assert joined["id"] == room["id"] and joined["my_role"] == "member"
    api.join(ben, room["invite_code"])  # second join is a no-op
    members = client.get(f"/api/rooms/{room['id']}/members", headers=asha["h"]).json()["members"]
    assert [(m["user"]["display_name"], m["role"]) for m in members] == [("Asha", "owner"), ("Ben", "member")]
    events = client.get(f"/api/rooms/{room['id']}/events", headers=asha["h"]).json()["events"]
    assert [e["type"] for e in events] == ["member.joined", "member.joined"]


def test_unknown_invite_code(api, client):
    ben = api.signup("Ben")
    r = client.post("/api/rooms/join", json={"invite_code": "NOPE-0000"}, headers=ben["h"])
    assert r.status_code == 404


def test_non_members_cannot_see_room(api, client):
    asha, eve = api.signup("Asha"), api.signup("Eve")
    room = api.room(asha)
    assert client.get(f"/api/rooms/{room['id']}", headers=eve["h"]).status_code == 404
    assert client.get(f"/api/rooms/{room['id']}/events", headers=eve["h"]).status_code == 404


def test_list_my_rooms_like_discord(api, client):
    asha, ben = api.signup("Asha"), api.signup("Ben")
    r1 = api.room(asha, "Campus App Launch")
    r2 = api.room(ben, "Hackathon Site")
    api.join(asha, r2["invite_code"])
    rooms = client.get("/api/rooms", headers=asha["h"]).json()["rooms"]
    assert [(r["name"], r["my_role"]) for r in rooms] == [("Campus App Launch", "owner"), ("Hackathon Site", "member")]
    assert rooms[0]["id"] == r1["id"]


def test_settings_mentor_only_partial_update(api, client):
    asha, ben = api.signup("Asha"), api.signup("Ben")
    room = api.room(asha)
    api.join(ben, room["invite_code"])
    url = f"/api/rooms/{room['id']}/settings"

    r = client.patch(url, json={"lease_minutes": 2}, headers=ben["h"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"

    r = client.patch(url, json={"require_approval": False, "lease_minutes": 10}, headers=asha["h"])
    assert r.status_code == 200
    s = r.json()["settings"]
    assert s["require_approval"] is False and s["lease_minutes"] == 10

    ev = client.get(f"/api/rooms/{room['id']}/events?types=room.settings_changed", headers=asha["h"]).json()["events"]
    assert ev[0]["payload"]["changed"] == ["lease_minutes", "require_approval"]

    assert client.patch(url, json={"lease_minutes": 0}, headers=asha["h"]).status_code == 422
    assert client.patch(url, json={"bogus": 1}, headers=asha["h"]).status_code == 422


def test_owner_promotes_member_to_mentor(api, client):
    asha, ben, chen = api.signup("Asha"), api.signup("Ben"), api.signup("Chen")
    room = api.room(asha)
    api.join(ben, room["invite_code"])
    api.join(chen, room["invite_code"])
    base = f"/api/rooms/{room['id']}/members"

    assert client.patch(f"{base}/{chen['id']}", json={"role": "mentor"}, headers=ben["h"]).status_code == 403
    r = client.patch(f"{base}/{ben['id']}", json={"role": "mentor"}, headers=asha["h"])
    assert r.status_code == 200 and r.json()["role"] == "mentor"
    # A mentor can now change settings, but still can't change roles.
    assert client.patch(f"/api/rooms/{room['id']}/settings", json={"lease_minutes": 2}, headers=ben["h"]).status_code == 200
    assert client.patch(f"{base}/{chen['id']}", json={"role": "mentor"}, headers=ben["h"]).status_code == 403
    # The owner's role is fixed.
    assert client.patch(f"{base}/{asha['id']}", json={"role": "member"}, headers=asha["h"]).status_code == 409
    assert client.patch(f"{base}/{ben['id']}", json={"role": "owner"}, headers=asha["h"]).status_code == 422


# --- Agents -----------------------------------------------------------------------------


def _create_agent(client, user, room_id, name="Asha's Claude", tool="claude_code", role="planner"):
    r = client.post(f"/api/rooms/{room_id}/agents", json={"name": name, "tool": tool, "role": role}, headers=user["h"])
    assert r.status_code == 201, r.text
    return r.json()


def test_create_agent_returns_token_once_and_snippets(api, client, db):
    from app.auth import hash_token
    from app.models import Agent

    asha = api.signup("Asha")
    room = api.room(asha)
    body = _create_agent(client, asha, room["id"])
    token, agent = body["token"], body["agent"]
    assert token.startswith("bat_")
    assert agent["tool"] == "claude_code" and agent["role"] == "planner" and agent["online"] is False
    assert re.fullmatch(r"#[0-9A-F]{6}", agent["color"])

    stored = db.execute(select(Agent.token_hash)).scalar_one()
    assert stored == hash_token(token) and token not in stored

    snips = body["config"]["snippets"]
    assert body["config"]["mcp_url"] == MCP_URL
    assert snips["claude_code"]["command"] == (
        f'claude mcp add --transport http baton {MCP_URL} --header "Authorization: Bearer {token}"'
    )
    assert 'bearer_token_env_var = "BATON_TOKEN"' in snips["codex"]["config_toml"]
    assert snips["codex"]["env"] == f"export BATON_TOKEN={token}"
    assert f'"httpUrl": "{MCP_URL}"' in snips["gemini_cli"]["settings_json"]
    assert "get_room_context" in body["config"]["instructions_md"]

    # The config endpoint can't know the token, so it uses the placeholder.
    cfg = client.get(f"/api/rooms/{room['id']}/agents/{agent['id']}/config", headers=asha["h"]).json()
    assert token not in str(cfg)
    assert "<BATON_TOKEN>" in cfg["snippets"]["claude_code"]["command"]


def test_agents_get_distinct_colors(api, client):
    asha = api.signup("Asha")
    room = api.room(asha)
    a = _create_agent(client, asha, room["id"], "A", "claude_code")["agent"]
    b = _create_agent(client, asha, room["id"], "B", "codex", "reviewer")["agent"]
    assert a["color"] != b["color"]


def test_agent_token_rejected_on_rest(api, client):
    asha = api.signup("Asha")
    room = api.room(asha)
    token = _create_agent(client, asha, room["id"])["token"]
    r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "/mcp" in r.json()["error"]["message"]


def test_revoke_rules(api, client):
    asha, ben = api.signup("Asha"), api.signup("Ben")
    room = api.room(asha)
    api.join(ben, room["invite_code"])
    asha_agent = _create_agent(client, asha, room["id"])["agent"]
    ben_agent = _create_agent(client, ben, room["id"], "Ben's Codex", "codex", "reviewer")["agent"]
    base = f"/api/rooms/{room['id']}/agents"

    assert client.delete(f"{base}/{asha_agent['id']}", headers=ben["h"]).status_code == 403
    assert client.delete(f"{base}/{ben_agent['id']}", headers=ben["h"]).status_code == 204
    assert client.delete(f"{base}/{asha_agent['id']}", headers=asha["h"]).status_code == 204

    assert client.get(base, headers=asha["h"]).json()["agents"] == []
    all_agents = client.get(f"{base}?include_revoked=true", headers=asha["h"]).json()["agents"]
    assert {a["revoked"] for a in all_agents} == {True}
    members = client.get(f"/api/rooms/{room['id']}/members", headers=asha["h"]).json()["members"]
    assert all(m["agent_ids"] == [] for m in members)


def test_revoked_agent_token_no_longer_authenticates(api, client, db):
    from app.auth import agent_from_token

    asha = api.signup("Asha")
    room = api.room(asha)
    body = _create_agent(client, asha, room["id"])
    assert agent_from_token(db, body["token"]) is not None
    client.delete(f"/api/rooms/{room['id']}/agents/{body['agent']['id']}", headers=asha["h"])
    db.expire_all()
    assert agent_from_token(db, body["token"]) is None


# --- Events -----------------------------------------------------------------------------


def test_event_seq_is_gap_free_and_filterable(api, client):
    asha, ben = api.signup("Asha"), api.signup("Ben")
    room = api.room(asha)
    api.join(ben, room["invite_code"])
    _create_agent(client, ben, room["id"], "Ben's Codex", "codex", "reviewer")
    url = f"/api/rooms/{room['id']}/events"

    events = client.get(url, headers=asha["h"]).json()
    assert [e["seq"] for e in events["events"]] == [1, 2, 3]
    assert events["latest_seq"] == 3
    assert [e["type"] for e in events["events"]] == ["member.joined", "member.joined", "agent.created"]
    assert events["events"][2]["summary"] == "Ben added agent Ben's Codex (codex, reviewer)"
    assert events["events"][2]["actor"]["name"] == "Ben"

    later = client.get(f"{url}?since_seq=2", headers=asha["h"]).json()["events"]
    assert [e["seq"] for e in later] == [3]
    page = client.get(f"{url}?limit=2", headers=asha["h"]).json()
    assert len(page["events"]) == 2 and page["has_more"] is True


def test_concurrent_events_get_unique_sequential_seqs(api, database):
    """Many writers at once must still produce 1..N with no gaps or duplicates."""
    from app.db import SessionLocal
    from app.models import Event
    from app.services.events import SYSTEM_ACTOR, append_event

    asha = api.signup("Asha")
    room_id = uuid.UUID(api.room(asha)["id"])  # seq 1
    errors = []

    def writer():
        try:
            with SessionLocal() as s:
                for _ in range(10):
                    append_event(s, room_id, "test.ping", SYSTEM_ACTOR, "ping")
                    s.commit()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with SessionLocal() as s:
        seqs = sorted(s.execute(select(Event.seq).where(Event.room_id == room_id)).scalars())
    assert seqs == list(range(1, 82))


def test_demo_session_signs_in_seeded_user(api, client, db):
    from app.models import Room

    asha = api.signup("Asha")
    room = api.room(asha)
    assert client.post("/api/session/demo", json={"display_name": "Asha"}).status_code == 404
    db.get(Room, __import__("uuid").UUID(room["id"])).is_demo = True
    db.commit()
    r = client.post("/api/session/demo", json={"display_name": "asha"})
    assert r.status_code == 200 and r.json()["user"]["id"] == asha["id"]
