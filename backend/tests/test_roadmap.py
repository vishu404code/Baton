"""Roadmap per AI tool + live activity: what each tool is told when it starts, and what it hears about the others."""


def _tasks():
    return [
        {"title": "Research the market", "owner": "chatgpt", "description": "Find three competitors.", "done_when": "notes saved"},
        {"title": "Build the API", "owner": "claude", "description": "REST endpoints for tasks.", "done_when": "tests pass", "depends_on": [1], "area": "backend/"},
        {"title": "Build the UI", "owner": "antigravity", "description": "Screens on top of the API.", "depends_on": [2], "area": "frontend/"},
    ]


def test_roadmap_briefings_and_live_activity(world, client):
    asha, claude, codex = world.asha, world.claude["token"], world.codex["token"]
    base = f"/api/rooms/{world.room_id}"
    r = client.post(f"{base}/roadmap", json={"tasks": _tasks(), "replace": True}, headers=asha["h"])
    assert r.status_code == 201 and [t["owner_tool"] for t in r.json()["tasks"]] == ["codex", "claude_code", "antigravity"]
    bad = client.post(f"{base}/roadmap", json={"tasks": [{"title": "x", "owner": "siri"}]}, headers=asha["h"])
    assert bad.status_code == 400 and "Unknown tool" in bad.json()["error"]["message"]

    hc = {"Authorization": f"Bearer {claude}"}
    hx = {"Authorization": f"Bearer {codex}"}
    first = client.get("/api/hooks/briefing?first=true", headers=hc).json()
    assert "YOUR TASK: 2. Build the API" in first["text"] and "waits for task 1" in first["text"] and "<- YOURS" in first["text"]
    # Nothing new since: silent (costs the tool nothing).
    assert client.get(f"/api/hooks/briefing?since={first['seq']}", headers=hc).json()["text"] == ""

    # ChatGPT finishes task 1; Claude hears it at its next prompt and its own task unblocks.
    assert client.patch(f"{base}/roadmap/1", json={"status": "done", "note": "3 competitors listed"}, headers=asha["h"]).status_code == 200
    upd = client.get(f"/api/hooks/briefing?since={first['seq']}", headers=hc).json()
    assert "Task 1" in upd["text"] and "done" in upd["text"]

    # Claude edits a file in its folder: task 2 starts by itself, and the other tool is told.
    assert client.post("/api/hooks/activity", json={"event": "edit", "summary": "edited backend/api.py", "path": "backend/api.py"}, headers=hc).status_code == 202
    tasks = {t["number"]: t for t in client.get(f"{base}/roadmap", headers=asha["h"]).json()["tasks"]}
    assert tasks[2]["status"] == "in_progress"
    heard = client.get(f"/api/hooks/briefing?since={upd['seq']}", headers=hx).json()["text"]
    assert "edited backend/api.py" in heard
    assert "backend/api.py" not in client.get(f"/api/hooks/briefing?since={upd['seq']}", headers=hc).json()["text"]  # not echoed to itself

    live = client.get(f"{base}/activity", headers=asha["h"]).json()
    claude_card = next(t for t in live["tools"] if t["tool"] == "claude_code")
    assert claude_card["last"]["summary"].endswith("edited backend/api.py")
    assert "Roadmap" in client.get(f"{base}/context", headers=asha["h"]).json()["handoff_markdown"]
    assert client.get("/api/hooks/briefing", headers={"Authorization": "Bearer bat_wrong"}).status_code == 401


def test_hook_script_reports_everything_a_tool_does():
    """Live shows every kind of action: prompts, edits, reads, searches and every shell command (even ls)."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("baton_hook", Path(__file__).resolve().parents[1] / "app" / "data" / "baton_hook.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    proj = "/tmp/p"
    d = h.describe
    assert d("claude_code", {"tool_name": "Edit", "tool_input": {"file_path": "/tmp/p/backend/api.py"}}, proj) == ("edit", "edited backend/api.py", "backend/api.py")
    assert d("claude_code", {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}, proj)[0:2] == ("command", "ran: ls -la")
    assert d("claude_code", {"tool_name": "Read", "tool_input": {"file_path": "/tmp/p/README.md"}}, proj)[0] == "read"
    assert d("claude_code", {"tool_name": "Grep", "tool_input": {"pattern": "def main"}}, proj)[1] == "searched for def main"
    assert d("antigravity", {"toolCall": {"name": "run_command", "args": {"CommandLine": "npm test"}}}, proj)[1] == "ran: npm test"
    assert d("antigravity", {"toolCall": {"name": "view_file", "args": {"AbsolutePath": "/tmp/p/App.tsx"}}}, proj)[1] == "read App.tsx"
    assert d("codex", {"tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch\n*** Add File: notes.md\n+x\n*** End Patch"}}, proj)[1] == "edited notes.md"
    assert d("claude_code", {"tool_name": "mcp__baton__update_task", "tool_input": {}}, proj) is None


def test_gemini_cli_hooks_are_installed_and_understood(tmp_path, monkeypatch):
    """Google's Gemini CLI joins the pipeline like the others: hooks in ~/.gemini/settings.json, JSON-only replies."""
    import importlib.util
    import json
    from pathlib import Path

    monkeypatch.setenv("BATON_HOME", str(tmp_path))
    from app import tool_connect as tc

    (tmp_path / ".gemini").mkdir()
    (tmp_path / ".gemini" / "settings.json").write_text(json.dumps({"mcpServers": {"keep": {"httpUrl": "x"}}, "theme": "dark"}))
    assert tc.install_hook("gemini_cli", "bat_x", "http://127.0.0.1:8765", "/tmp/p") == ["~/.gemini/settings.json (hooks)"]
    data = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
    assert data["theme"] == "dark" and "keep" in data["mcpServers"]  # existing settings untouched
    assert set(data["hooks"]) == {"SessionStart", "BeforeAgent", "AfterTool", "AfterAgent"}
    assert data["hooks"]["BeforeAgent"][0]["hooks"][0]["timeout"] == 5000
    assert tc.hooks_installed()["gemini_cli"] is True
    tc.install_hook("gemini_cli", "bat_y", "http://127.0.0.1:8765", "/tmp/p")  # re-running never duplicates
    assert len(json.loads((tmp_path / ".gemini" / "settings.json").read_text())["hooks"]["AfterTool"]) == 1

    spec = importlib.util.spec_from_file_location("baton_hook", Path(__file__).resolve().parents[1] / "app" / "data" / "baton_hook.py")
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    d = h.describe
    assert d("gemini_cli", {"tool_name": "write_file", "tool_input": {"file_path": "/tmp/p/page.html"}}, "/tmp/p") == ("edit", "edited page.html", "page.html")
    assert d("gemini_cli", {"tool_name": "run_shell_command", "tool_input": {"command": "python3 app.py"}}, "/tmp/p")[1] == "ran: python3 app.py"
    assert d("gemini_cli", {"tool_name": "read_file", "tool_input": {"file_path": "/tmp/p/index.json"}}, "/tmp/p")[0] == "read"
