"""Connect the AI tools on this computer to Baton's MCP server, and tell each one to use it.

For every tool this (1) creates a Baton agent with its own token, (2) writes the tool's MCP config so it
connects by itself, and (3) adds a short standing instruction (global CLAUDE.md / AGENTS.md / GEMINI.md) so
the tool calls get_handoff first and save_context when it finishes, without you prompting it.

Safe by design: only the `baton` entry / the marked Baton block is added or replaced, everything else in
the files is kept, and a one-time `.baton-backup` copy is made before the first change.

    python -m app.tool_connect [--url http://127.0.0.1:8765/mcp]
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from app.agent_instructions import INSTRUCTIONS_MD
from app.models import Agent
from app.services import rooms as room_svc

BEGIN, END = "<!-- BATON:BEGIN -->", "<!-- BATON:END -->"

TOOLS = {
    "claude_code": {"label": "Claude Code", "agent": "Claude Code"},
    "codex": {"label": "Codex / ChatGPT app", "agent": "Codex (ChatGPT)"},
    "antigravity": {"label": "Antigravity", "agent": "Antigravity"},
    "gemini_cli": {"label": "Gemini CLI", "agent": "Gemini CLI"},
}


def home() -> Path:
    return Path(os.environ.get("BATON_HOME") or Path.home())


def _backup(p: Path) -> None:
    if p.exists():
        dst = p.with_name(p.name + ".baton-backup")
        if not dst.exists():
            shutil.copy2(p, dst)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    _backup(p)
    p.write_text(text)


def upsert_block(path: Path, body: str) -> None:
    """Add (or replace) the marked Baton block in a markdown instruction file, keeping everything else."""
    old = path.read_text() if path.exists() else ""
    old = re.sub(rf"\n?{re.escape(BEGIN)}.*?{re.escape(END)}\n?", "\n", old, flags=re.S).rstrip()
    new = (old + "\n\n" if old else "") + f"{BEGIN}\n{body.strip()}\n{END}\n"
    _write(path, new)


def merge_json_server(path: Path, entry: dict) -> None:
    data = {}
    if path.exists() and path.read_text().strip():
        try:
            data = json.loads(path.read_text())
        except ValueError as e:
            raise RuntimeError(f"{path} is not valid JSON ({e}); left unchanged") from None
    data.setdefault("mcpServers", {})["baton"] = entry
    _write(path, json.dumps(data, indent=2) + "\n")


def write_codex_toml(path: Path, url: str, token: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    out, skipping = [], False
    for ln in lines:
        if ln.strip().startswith("["):
            skipping = bool(re.match(r"\[\s*mcp_servers\.baton(\.|\])", ln.strip()))
        if not skipping:
            out.append(ln)
    text = "\n".join(out).rstrip()
    block = (
        "[mcp_servers.baton]\n"
        f'url = "{url}"\n'
        f'http_headers = {{ "Authorization" = "Bearer {token}" }}\n'
        'default_tools_approval_mode = "approve"\n'
    )
    _write(path, (text + "\n\n" if text else "") + block)


def find_claude() -> str | None:
    p = shutil.which("claude")
    if p:
        return p
    hits = sorted(glob.glob(str(Path.home() / "Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")))
    return hits[-1] if hits else None


def connect_claude(url: str, token: str) -> str:
    claude = find_claude()
    if not claude:
        return "skipped: the claude command wasn't found. Run: claude mcp add --scope user --transport http baton " + url + ' --header "Authorization: Bearer <token>"'
    subprocess.run([claude, "mcp", "remove", "baton", "--scope", "user"], capture_output=True, timeout=60)
    r = subprocess.run(
        [claude, "mcp", "add", "--scope", "user", "--transport", "http", "baton", url, "--header", f"Authorization: Bearer {token}"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300] or "claude mcp add failed")
    return "claude mcp add (user scope)"


def connect_tool(tool: str, url: str, token: str) -> list[str]:
    """Write the config + instructions for one tool. Returns what was changed."""
    h, done = home(), []
    if tool == "claude_code":
        done.append(connect_claude(url, token))
        upsert_block(h / ".claude" / "CLAUDE.md", INSTRUCTIONS_MD)
        done.append("~/.claude/CLAUDE.md")
    elif tool == "codex":
        write_codex_toml(h / ".codex" / "config.toml", url, token)
        upsert_block(h / ".codex" / "AGENTS.md", INSTRUCTIONS_MD)
        done += ["~/.codex/config.toml", "~/.codex/AGENTS.md"]
    elif tool == "gemini_cli":
        merge_json_server(h / ".gemini" / "settings.json", {"httpUrl": url, "headers": {"Authorization": f"Bearer {token}"}})
        upsert_block(h / ".gemini" / "GEMINI.md", INSTRUCTIONS_MD)
        done += ["~/.gemini/settings.json", "~/.gemini/GEMINI.md"]
    elif tool == "antigravity":
        merge_json_server(h / ".gemini" / "config" / "mcp_config.json", {"serverUrl": url, "headers": {"Authorization": f"Bearer {token}"}})
        upsert_block(h / ".gemini" / "GEMINI.md", INSTRUCTIONS_MD)
        done += ["~/.gemini/config/mcp_config.json", "~/.gemini/GEMINI.md"]
    else:
        raise ValueError(f"unknown tool {tool}")
    return done


def connect_all(db, room, owner, url: str, tools: list[str] | None = None) -> dict[str, dict]:
    """Create fresh agents + tokens in `room` and wire every tool. One failing tool never blocks the others."""
    results: dict[str, dict] = {}
    for tool in tools or list(TOOLS):
        meta = TOOLS[tool]
        for old in db.execute(select(Agent).where(Agent.room_id == room.id, Agent.name == meta["agent"], Agent.revoked_at.is_(None))).scalars():
            room_svc.revoke_agent(db, room, old, owner, "owner")
        agent, token = room_svc.create_agent(db, room, owner, meta["agent"], tool, "planner")
        db.commit()
        try:
            results[tool] = {"ok": True, "changed": connect_tool(tool, url, token), "agent": agent.name}
        except Exception as e:  # noqa: BLE001
            results[tool] = {"ok": False, "error": str(e), "agent": agent.name}
    return results


def main() -> int:
    from app.db import SessionLocal, init_db
    from app.services import bootstrap

    url = "http://127.0.0.1:8765/mcp"
    if "--url" in sys.argv:
        url = sys.argv[sys.argv.index("--url") + 1]
    init_db()
    with SessionLocal() as db:
        owner, room = bootstrap.ensure_local_workspace(db)
        res = connect_all(db, room, owner, url)
    for tool, r in res.items():
        print(("OK   " if r["ok"] else "FAIL ") + TOOLS[tool]["label"] + ": " + (", ".join(r["changed"]) if r["ok"] else r["error"]))
    return 0 if all(r["ok"] for r in res.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
