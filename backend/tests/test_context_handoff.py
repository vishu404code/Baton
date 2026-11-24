"""The core promise: one AI tool saves what it did, the next one reads it without being re-prompted."""

import json

import anyio

from tests.test_mcp_flow import call  # noqa: F401  (MCP-over-HTTP helper)


def test_context_flows_from_one_tool_to_the_next_over_mcp(world, live_server, client):
    claude, codex = world.claude["token"], world.codex["token"]

    err, brief = call(live_server, codex, "get_handoff")
    assert not err, brief
    md = brief["markdown"]
    assert "Campus app launch brief" not in md and "Launch the campus app" in md  # goal from the brief
    assert "Decision 2 (Launch date): We launch on 10 January." in md
    assert "nothing logged yet" in md

    err, saved = call(live_server, codex, "save_context", {
        "summary": "Drafted the launch checklist in docs/launch.md.", "next_steps": "Review the checklist against Decision 2.",
        "files": ["docs/launch.md"], "kind": "progress"})
    assert not err and saved["saved"] is True

    # A different tool starts a fresh chat and is instantly up to date, with no prompt from the user.
    err, brief2 = call(live_server, claude, "get_handoff")
    md2 = brief2["markdown"]
    assert "Ben's Codex" in md2 and "Drafted the launch checklist" in md2
    assert "Next: Review the checklist against Decision 2." in md2 and "docs/launch.md" in md2
    assert "Review the checklist against Decision 2." in md2.split("## Suggested next steps")[1]

    # The UI sees it too, live, and a human can add a note.
    r = client.post(f"/api/rooms/{world.room_id}/context", json={"summary": "Switching to Antigravity for the UI.", "next_steps": "Build the landing page."}, headers=world.asha["h"])
    assert r.status_code == 201
    ctx = client.get(f"/api/rooms/{world.room_id}/context", headers=world.asha["h"]).json()
    assert [e["author"] for e in ctx["entries"]] == ["Asha", "Ben's Codex"]
    assert "Switching to Antigravity" in ctx["handoff_markdown"]
    ev = client.get(f"/api/rooms/{world.room_id}/events?types=context.saved", headers=world.asha["h"]).json()["events"]
    assert len(ev) == 2


def test_save_context_validates_and_is_open_to_every_role(world, live_server):
    err, msg = call(live_server, world.codex["token"], "save_context", {"summary": "   "})
    assert err and "summary is empty" in msg
    # An observer can't claim tasks but can still share context.
    import httpx
    r = httpx.post(f"http://{live_server.split('//')[1]}/api/rooms/{world.room_id}/agents", json={"name": "Watcher", "role": "observer", "tool": "gemini_cli"}, headers=world.asha["h"])
    tok = r.json()["token"]
    err, out = call(live_server, tok, "save_context", {"summary": "Read the plan; looks consistent."})
    assert not err and out["saved"]


def test_connect_writes_each_tools_config_safely(world, db, tmp_path, monkeypatch):
    import json as _json

    from app import tool_connect as tc
    from app.models import Room, User

    monkeypatch.setenv("BATON_HOME", str(tmp_path))
    monkeypatch.setattr(tc, "find_claude", lambda: None)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text('notify = ["x"]\n\n[marketplaces.a]\nsource = "s"\n\n[mcp_servers.baton]\nurl = "old"\n\n[plugins.b]\nenabled = true\n')
    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".gemini" / "settings.json").write_text(_json.dumps({"theme": "dark", "mcpServers": {"other": {"httpUrl": "http://x"}}}))
    (tmp_path / ".codex" / "AGENTS.md").write_text("# my rules\nbe nice\n")

    import uuid
    room = db.get(Room, uuid.UUID(world.room_id))
    owner = db.get(User, room.owner_id)
    for _ in range(2):  # running twice must not duplicate anything
        res = tc.connect_all(db, room, owner, "http://127.0.0.1:8765/mcp")
        assert res["codex"]["ok"] and res["gemini_cli"]["ok"] and res["antigravity"]["ok"] and res["claude_code"]["ok"]

    toml = (tmp_path / ".codex" / "config.toml").read_text()
    assert toml.count("[mcp_servers.baton]") == 1 and 'url = "http://127.0.0.1:8765/mcp"' in toml and "old" not in toml
    assert 'notify = ["x"]' in toml and "[marketplaces.a]" in toml and "[plugins.b]" in toml  # others kept
    assert "Bearer bat_" in toml and 'default_tools_approval_mode = "approve"' in toml
    g = _json.loads((tmp_path / ".gemini" / "settings.json").read_text())
    assert g["theme"] == "dark" and "other" in g["mcpServers"] and g["mcpServers"]["baton"]["httpUrl"].endswith("/mcp")
    a = _json.loads((tmp_path / ".gemini" / "config" / "mcp_config.json").read_text())
    assert a["mcpServers"]["baton"]["serverUrl"].endswith("/mcp") and a["mcpServers"]["baton"]["headers"]["Authorization"].startswith("Bearer bat_")
    for f in (".codex/AGENTS.md", ".gemini/GEMINI.md", ".claude/CLAUDE.md"):
        text = (tmp_path / f).read_text()
        assert text.count("<!-- BATON:BEGIN -->") == 1 and "get_handoff" in text
    assert "be nice" in (tmp_path / ".codex" / "AGENTS.md").read_text()
    assert (tmp_path / ".codex" / "config.toml.baton-backup").exists() and (tmp_path / ".gemini" / "settings.json.baton-backup").exists()


def test_live_demo_runs_and_each_tool_reads_the_earlier_ones(client, monkeypatch):
    import time as _t

    from app.services import demo

    from app.config import get_settings

    monkeypatch.setattr(demo.time, "sleep", lambda s: None)
    monkeypatch.setattr(get_settings(), "baton_local_mode", True)
    local = client.post("/api/session/local").json()
    h = {"Authorization": f"Bearer {local['token']}"}
    rooms = client.get("/api/rooms", headers=h).json()["rooms"]
    room = next(r for r in rooms if r["name"] == demo.DEMO_ROOM_NAME)
    base = f"/api/rooms/{room['id']}/context"
    assert client.post(f"/api/rooms/{local['room_id']}/context/demo/start", headers=h).status_code == 403

    assert client.post(f"{base}/demo/start", headers=h).json()["started"] is True
    deadline = _t.time() + 20
    while _t.time() < deadline and not client.get(f"{base}/demo", headers=h).json()["done"]:
        _t.sleep(0.05)
    st = client.get(f"{base}/demo", headers=h).json()
    assert st["done"] and len(st["transcript"]) == len(demo.STEPS)
    ctx = client.get(base, headers=h).json()
    assert [e["tool"] for e in ctx["entries"]][::-1] == [s["tool"] for s in demo.STEPS]
    assert "32,900" in ctx["handoff_markdown"]

    assert client.post(f"{base}/demo/reset", headers=h).status_code == 200
    assert client.get(base, headers=h).json()["entries"] == []
