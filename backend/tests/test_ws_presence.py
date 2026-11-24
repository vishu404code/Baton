"""Milestone 4: WebSocket live events (with replay) and presence."""

import json
import logging

import pytest
from starlette.websockets import WebSocketDisconnect


def _recv(ws, kind=None, type_=None, limit=50):
    """Read messages until one matches kind/type (skipping others)."""
    for _ in range(limit):
        msg = json.loads(ws.receive_text())
        if kind and msg["kind"] != kind:
            continue
        if type_ and msg.get("event", {}).get("type") != type_:
            continue
        return msg
    raise AssertionError(f"no {kind}/{type_} message")


def _url(w, user, since=None):
    q = f"?token={user['token']}" + (f"&since_seq={since}" if since is not None else "")
    return f"/ws/rooms/{w.room_id}{q}"


def test_bad_token_non_member_and_unknown_room_are_closed(world, client, api):
    eve = api.signup("Eve")
    for url, code in [
        (f"/ws/rooms/{world.room_id}?token=bs_nope", 4401),
        (f"/ws/rooms/{world.room_id}?token={eve['token']}", 4403),
        (f"/ws/rooms/00000000-0000-0000-0000-000000000000?token={eve['token']}", 4404),
    ]:
        with client.websocket_connect(url) as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            assert exc.value.code == code


def test_hello_then_full_replay_in_order(world, client):
    with client.websocket_connect(_url(world, world.asha, since=0)) as ws:
        hello = _recv(ws, "hello")
        assert hello["room_id"] == world.room_id
        latest = hello["latest_seq"]
        assert {u["display_name"] for u in hello["presence"]["users"]} == {"Asha", "Ben"}
        seqs = []
        while len(seqs) < latest:
            msg = _recv(ws, "event")
            if msg["event"]["seq"] is not None:
                seqs.append(msg["event"]["seq"])
        assert seqs == list(range(1, latest + 1))


def test_replay_only_after_since_seq_then_live(world, client):
    room = client.get(f"/api/rooms/{world.room_id}", headers=world.asha["h"]).json()
    since = room["latest_seq"] - 2
    with client.websocket_connect(_url(world, world.asha, since=since)) as ws:
        _recv(ws, "hello")
        replayed = [_recv(ws, "event")["event"]["seq"] for _ in range(2)]
        replayed = [s for s in replayed if s is not None]
        assert replayed[0] == since + 1
        # A live change made over REST arrives on the socket.
        client.post(f"/api/records/{world.dec2['record']['id']}/comments", json={"text": "Live?"}, headers=world.ben["h"])
        live = _recv(ws, "event", "comment.added")
        assert live["event"]["seq"] == room["latest_seq"] + 1
        assert live["event"]["summary"] == "Ben commented on Decision 2"


def test_resume_and_ping(world, client):
    with client.websocket_connect(_url(world, world.asha, since=10**6)) as ws:
        _recv(ws, "hello")
        ws.send_text(json.dumps({"kind": "ping"}))
        assert _recv(ws, "pong")["kind"] == "pong"
        ws.send_text(json.dumps({"kind": "resume", "since_seq": 0}))
        # Nothing is re-sent: the client already claimed to have seen up to a huge seq.
        ws.send_text(json.dumps({"kind": "ping"}))
        assert _recv(ws)["kind"] == "pong"


def test_two_members_see_the_same_live_stream(world, client):
    latest = client.get(f"/api/rooms/{world.room_id}", headers=world.asha["h"]).json()["latest_seq"]
    with client.websocket_connect(_url(world, world.asha, since=latest)) as a, client.websocket_connect(_url(world, world.ben, since=latest)) as b:
        _recv(a, "hello")
        _recv(b, "hello")
        client.patch(f"/api/rooms/{world.room_id}/settings", json={"lease_minutes": 20}, headers=world.asha["h"])
        ea = _recv(a, "event", "room.settings_changed")["event"]
        eb = _recv(b, "event", "room.settings_changed")["event"]
        assert ea["seq"] == eb["seq"] and ea["payload"]["changed"] == ["lease_minutes"]


def test_presence_users_online_while_connected(world, client):
    url = f"/api/rooms/{world.room_id}/presence"
    assert {u["display_name"]: u["online"] for u in client.get(url, headers=world.asha["h"]).json()["users"]} == {"Asha": False, "Ben": False}
    with client.websocket_connect(_url(world, world.ben, since=10**6)) as ws:
        _recv(ws, "hello")
        p = client.get(url, headers=world.asha["h"]).json()
        assert {u["display_name"]: u["online"] for u in p["users"]} == {"Asha": False, "Ben": True}
        members = client.get(f"/api/rooms/{world.room_id}/members", headers=world.asha["h"]).json()["members"]
        assert {m["user"]["display_name"]: m["online"] for m in members}["Ben"] is True
    p = client.get(url, headers=world.asha["h"]).json()
    assert all(not u["online"] for u in p["users"])


def test_presence_shows_agent_working_on(world, client, db, agent_of):
    from app.services import claims as claim_svc

    claude = agent_of(world.claude)
    from app.models import utcnow

    claude.last_seen_at = utcnow()
    claim_svc.claim_task(db, claude, "Task 1")
    db.commit()
    agents = client.get(f"/api/rooms/{world.room_id}/presence", headers=world.asha["h"]).json()["agents"]
    me = next(a for a in agents if a["name"] == "Asha's Claude")
    assert me["online"] is True
    assert me["working_on"]["label"] == "Task 1" and me["working_on"]["lease_expires_at"]


def test_presence_changed_is_pushed_when_someone_joins(world, client):
    with client.websocket_connect(_url(world, world.asha, since=10**6)) as a:
        _recv(a, "hello")
        with client.websocket_connect(_url(world, world.ben, since=10**6)) as b:
            _recv(b, "hello")
            # The first update may be Asha's own arrival; wait for the one showing Ben.
            for _ in range(5):
                msg = _recv(a, "event", "presence.changed")
                online = {u["display_name"]: u["online"] for u in msg["event"]["payload"]["users"]}
                if online["Ben"]:
                    break
            assert online == {"Asha": True, "Ben": True} and msg["event"]["seq"] is None


def test_tokens_are_redacted_from_logs():
    from app.logging_filters import RedactTokens

    rec = logging.LogRecord("uvicorn.error", logging.INFO, "", 0, '%s - "WebSocket %s" [accepted]', ("1.2.3.4", "/ws/rooms/x?token=bs_abcdef123456&since_seq=4"), None)
    RedactTokens().filter(rec)
    assert "bs_abcdef123456" not in rec.getMessage() and "token=[redacted]" in rec.getMessage()
    assert "since_seq=4" in rec.getMessage()
