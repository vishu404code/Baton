"""Shared progress log + the handoff briefing every connected AI tool reads first."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import ContextEntry, Record, Room
from app.services import ledger
from app.services.events import append_event, iso

KINDS = ("progress", "decision", "question", "note")
TOOL_LABEL = {"claude_code": "Claude Code", "codex": "Codex / ChatGPT", "antigravity": "Antigravity", "gemini_cli": "Gemini CLI", "user": "You", "other": "AI tool"}


def entry_out(e: ContextEntry) -> dict:
    return {
        "id": str(e.id), "author": e.author, "tool": e.tool, "kind": e.kind, "summary": e.summary,
        "next_steps": e.next_steps, "files": e.files or [], "created_at": iso(e.created_at),
    }


def save_entry(db, room_id: uuid.UUID, *, author: str, tool: str, summary: str, actor: dict,
               next_steps: str | None = None, files: list[str] | None = None, kind: str = "progress") -> ContextEntry:
    e = ContextEntry(
        room_id=room_id, author=author[:80], tool=tool, kind=kind if kind in KINDS else "progress",
        summary=summary.strip()[:4000], next_steps=(next_steps or "").strip()[:2000] or None,
        files=[str(f)[:300] for f in (files or [])][:30],
    )
    db.add(e)
    db.flush()
    append_event(db, room_id, "context.saved", actor, f"{author} saved context: {e.summary[:100]}", {"entry": entry_out(e)})
    return e


def recent_entries(db, room_id: uuid.UUID, limit: int = 30) -> list[ContextEntry]:
    return list(db.execute(select(ContextEntry).where(ContextEntry.room_id == room_id).order_by(ContextEntry.created_at.desc()).limit(limit)).scalars())


def _snip(text: str, n: int = 200) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def build_handoff(db, room: Room, *, for_name: str | None = None) -> dict:
    """The briefing a tool reads first: goal, decisions, what exists, what others did, what to do next."""
    records = lambda t: db.execute(select(Record).where(Record.room_id == room.id, Record.type == t).order_by(Record.number)).scalars().all()  # noqa: E731
    cur = lambda r: ledger.current_revision(db, r).content or {}  # noqa: E731
    lines = [f"# Baton handoff: {room.name}", ""]
    lines.append(f"You ({for_name or 'an AI tool'}) are picking up shared work. Other AI tools may have worked on this already. "
                 "Read this, then continue; do not ask the user to re-explain.")
    brief = ledger.latest(db, room.id, "brief")
    lines += ["", "## Goal", _snip(cur(brief).get("body", ""), 900) if brief else "(no brief written yet)"]
    decisions = records("decision")
    lines += ["", "## Decisions (binding)"]
    lines += [f"- {ledger.label(d)} ({d.title}): {cur(d).get('statement', '')}" for d in decisions] or ["- none yet"]
    sources = records("source")
    if sources:
        lines += ["", "## Sources"] + [f"- {ledger.label(s)} ({s.title}): {_snip(cur(s).get('summary') or cur(s).get('text') or cur(s).get('url') or '', 140)}" for s in sources]
    tasks = records("task")
    lines += ["", "## Tasks and results so far"]
    for t in tasks:
        out = ledger.output_of(db, t)
        line = f"- {ledger.label(t)} [{t.status}] {t.title}"
        if out is not None:
            c = cur(out)
            line += f"\n    {ledger.label(out)} v{out.current_revision} [{out.status}]: " + _snip(c.get("body") or (f"{c.get('verdict')}: {c.get('comments')}" if c.get("verdict") else ""), 240)
        lines.append(line)
    if not tasks:
        lines.append("- no tasks yet")
    entries = recent_entries(db, room.id, 12)
    lines += ["", "## What other tools did recently (newest first)"]
    for e in entries:
        who = f"{e.author}" + ("" if TOOL_LABEL.get(e.tool, "") in e.author else f" ({TOOL_LABEL.get(e.tool, e.tool)})")
        lines.append(f"- {e.created_at.strftime('%d %b %H:%M')} UTC, {who} [{e.kind}]: {e.summary}")
        if e.next_steps:
            lines.append(f"    Next: {e.next_steps}")
        if e.files:
            lines.append(f"    Files: {', '.join(e.files[:8])}")
    if not entries:
        lines.append("- nothing logged yet. You are first: save_context as you go.")
    nxt = [e for e in entries if e.next_steps][:3]
    lines += ["", "## Suggested next steps"] + ([f"- {e.next_steps} (from {e.author})" for e in nxt] or ["- ask the user what to do, or claim an open task with list_tasks"])
    lines += ["", "## When you finish", "Call save_context(summary, next_steps, files) so the next tool continues from exactly here."]
    return {"room": room.name, "markdown": "\n".join(lines), "entries": [entry_out(e) for e in entries]}
