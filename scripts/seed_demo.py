"""Seed the "Campus App Launch" demo room and print how to connect agents.

Run inside the backend container (./start.sh does this for you):
    python scripts/seed_demo.py --if-empty   # seed only when the database has no rooms
    python scripts/seed_demo.py --print      # print invite code, demo users and agent configs

Demo agent tokens are written to .baton/demo.json (gitignored), because the database only
stores token hashes.
"""

from __future__ import annotations

import argparse
import uuid
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))  # when run from the repo root
sys.path.insert(0, "/app")  # inside the container

from sqlalchemy import func, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Approval, Record, Room, User, utcnow  # noqa: E402
from app.serializers import actor_user  # noqa: E402
from app.services import claims as claim_svc  # noqa: E402
from app.services import ledger  # noqa: E402
from app.services import rooms as room_svc  # noqa: E402
from app.services import submissions as sub_svc  # noqa: E402
from app.services.agent_config import build_config  # noqa: E402
from app.services.events import append_event  # noqa: E402

DEMO_FILE = Path(os.environ.get("BATON_DEMO_FILE", "/app/.baton/demo.json" if Path("/app").exists() else ".baton/demo.json"))
INVITE = "CAMPUS-7KQ2"


def _record(db, room, user, type_, title, content):
    status = "open" if type_ == "task" else "approved"
    rec, rev = ledger.create_record(db, room.id, type_, title, content, author_user_id=user.id, status=status)
    append_event(
        db, room.id, "revision.created", actor_user(user, "owner"),
        f"{user.display_name} created {ledger.label(rec)} \"{rec.title}\"",
        {"record": ledger.record_ref(rec) | {"type": type_}}, record_ids=[rec.id],
    )
    if type_ == "task":
        append_event(
            db, room.id, "task.created", actor_user(user, "owner"),
            f"{user.display_name} created {ledger.label(rec)} \"{rec.title}\" for a {content['role']}",
            {"task": ledger.record_ref(rec)}, record_ids=[rec.id],
        )
    return rec, rev


def seed() -> dict:
    with SessionLocal() as db:
        asha, ben, chen = (User(display_name=n) for n in ("Asha", "Ben", "Chen"))
        db.add_all([asha, ben, chen])
        db.flush()
        room = room_svc.create_room(db, asha, "Campus App Launch", is_demo=True, invite_code=INVITE)
        room_svc.add_member(db, room, ben)
        member, _ = room_svc.add_member(db, room, chen)
        member.role = "mentor"

        brief, brief_v = _record(db, room, asha, "brief", "Campus app launch brief", {
            "body": (
                "## Goal\nLaunch the new campus app to every student this term.\n\n"
                "## Must have\n- A launch plan with dates, channels and owners\n- A volunteer rota for launch week\n"
                "- An FAQ for the help desk\n\n## Constraints\nFollow the decisions below. Cite sources for every date and number."
            ),
        })
        dec1, dec1_v = _record(db, room, asha, "decision", "Platforms", {
            "statement": "We launch on iOS and Android at the same time; no web version at launch.",
            "rationale": "92% of students use a smartphone (Source 2).",
        })
        dec2, dec2_v = _record(db, room, asha, "decision", "Launch date", {
            "statement": "We launch on 10 January.",
            "rationale": "Before the spring term starts on 13 January (Source 1).",
        })
        dec3, dec3_v = _record(db, room, asha, "decision", "Volunteers", {
            "statement": "Launch week is staffed by 12 student volunteers in 2 shifts per day.",
            "rationale": "Student union offered 12 volunteers (Source 3).",
        })
        src1, _ = _record(db, room, asha, "source", "Academic calendar 2026-27", {
            "url": "https://example.edu/academic-calendar", "summary": "Spring term starts 13 January; exams 2-12 January.",
        })
        src2, _ = _record(db, room, asha, "source", "Student device survey", {
            "text": "Survey of 1,240 students, Oct 2026: 92% own a smartphone (58% iOS, 42% Android).",
        })
        src3, _ = _record(db, room, asha, "source", "Student union email", {
            "text": "The student union can provide 12 volunteers for launch week, mornings and afternoons.",
        })
        task1, _ = _record(db, room, asha, "task", "Write launch plan", {
            "description": "Write the launch plan: timeline, channels, owners. Base every date on the decisions and cite sources.",
            "role": "planner",
        })
        _record(db, room, asha, "task", "Review launch plan", {
            "description": "Review the launch plan against the brief, decisions and sources. Give a verdict and comments.",
            "role": "reviewer", "review_of_task_id": str(task1.id),
        })
        task3, _ = _record(db, room, asha, "task", "Draft volunteer rota", {
            "description": "Draft the launch-week volunteer rota following the volunteers decision.", "role": "planner",
        })
        _record(db, room, asha, "task", "Write help-desk FAQ", {
            "description": "Write a short FAQ for the help desk about the new app.", "role": "planner",
        })

        claude, claude_tok = room_svc.create_agent(db, room, asha, "Asha's Claude", "claude_code", "planner")
        codex, codex_tok = room_svc.create_agent(db, room, ben, "Ben's Codex", "codex", "reviewer")
        gemini, gemini_tok = room_svc.create_agent(db, room, chen, "Chen's Gemini", "gemini_cli", "planner")
        db.commit()

        # Independent, already-approved work: the volunteer rota depends on Decision 3 only,
        # so changing Decision 2 during the demo leaves it untouched.
        claim_svc.claim_task(db, gemini, "Task 3")
        db.commit()
        out = sub_svc.submit(
            db, gemini, "Task 3",
            {"body": (
                "## Launch-week volunteer rota\n| Day | Morning (6) | Afternoon (6) |\n|---|---|---|\n"
                "| Mon-Fri | Info stand, Library | Info stand, Canteen |\n\n12 volunteers, 2 shifts per day (Decision 3)."
            )},
            [str(brief_v.id), str(dec3_v.id)], [str(src3.id)], "seed-gemini-task3-1", "Volunteer rota",
        )
        assert out["status"] == "completed", out
        approval = db.execute(select(Approval).where(Approval.status == "pending")).scalar_one()
        approval.status, approval.decided_by_user_id, approval.decided_at = "approved", asha.id, utcnow()
        approval.comment = "Looks good."
        for rec_id in (approval.record_id, approval.task_id):
            db.get(Record, rec_id).status = "approved"
        append_event(
            db, room.id, "approval.decided", actor_user(asha, "owner"), "Asha approved Draft 3 v1 (volunteer rota)",
            {"approval": {"id": str(approval.id), "status": "approved", "comment": approval.comment}},
            record_ids=[approval.record_id, approval.task_id],
        )
        db.commit()

        demo = {
            "room_id": str(room.id),
            "room_name": room.name,
            "invite_code": room.invite_code,
            "users": ["Asha", "Ben", "Chen"],
            "agents": [
                {"id": str(claude.id), "name": claude.name, "tool": "claude_code", "role": "planner", "user": "Asha", "token": claude_tok},
                {"id": str(codex.id), "name": codex.name, "tool": "codex", "role": "reviewer", "user": "Ben", "token": codex_tok},
                {"id": str(gemini.id), "name": gemini.name, "tool": "gemini_cli", "role": "planner", "user": "Chen", "token": gemini_tok},
            ],
        }
    DEMO_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEMO_FILE.write_text(json.dumps(demo, indent=2))
    os.chmod(DEMO_FILE, 0o600)
    write_workspaces(demo)
    return demo


def write_workspaces(demo: dict) -> None:
    """Ready-made agent folders: `cd .baton/agents/claude && claude` and the agent is connected."""
    from app.agent_instructions import INSTRUCTIONS_MD

    url = get_settings().mcp_url
    base = DEMO_FILE.parent / "agents"
    for a in demo["agents"]:
        auth = {"Authorization": f"Bearer {a['token']}"}
        if a["tool"] == "claude_code":
            d = base / "claude"
            d.mkdir(parents=True, exist_ok=True)
            (d / ".mcp.json").write_text(json.dumps({"mcpServers": {"baton": {"type": "http", "url": url, "headers": auth}}}, indent=2))
            (d / "CLAUDE.md").write_text(INSTRUCTIONS_MD)
        elif a["tool"] == "codex":
            d = base / "codex"
            d.mkdir(parents=True, exist_ok=True)
            (d / "AGENTS.md").write_text(INSTRUCTIONS_MD)
            (d / "codex-config.toml").write_text(
                f'[mcp_servers.baton]\nurl = "{url}"\nbearer_token_env_var = "BATON_TOKEN"\ndefault_tools_approval_mode = "approve"\n'
            )
            (d / "env.sh").write_text(f"export BATON_TOKEN={a['token']}\n")
        elif a["tool"] == "gemini_cli":
            d = base / "gemini"
            (d / ".gemini").mkdir(parents=True, exist_ok=True)
            (d / ".gemini" / "settings.json").write_text(json.dumps({"mcpServers": {"baton": {"httpUrl": url, "headers": auth}}}, indent=2))
            (d / "GEMINI.md").write_text(INSTRUCTIONS_MD)


def print_info() -> None:
    if not DEMO_FILE.exists():
        print("No demo data file found. Run ./reset-demo.sh to seed the demo.")
        return
    demo = json.loads(DEMO_FILE.read_text())
    url = get_settings().mcp_url
    print(f"Demo room:    {demo['room_name']}")
    print(f"Invite code:  {demo['invite_code']}")
    print(f"Demo users:   {', '.join(demo['users'])}  (one-click sign-in in the UI)")
    print()
    from app.models import Agent

    with SessionLocal() as db:
        for a in demo["agents"]:
            agent = db.get(Agent, uuid.UUID(a["id"]))
            if agent is None:
                continue
            cfg = build_config(agent, a["token"])["snippets"]
            print(f"── {a['name']}  ({a['tool']}, {a['role']}, owned by {a['user']}) ──")
            if a["tool"] == "claude_code":
                print(f"  {cfg['claude_code']['command']}")
            elif a["tool"] == "codex":
                print("  Add to ~/.codex/config.toml:")
                print("    " + cfg["codex"]["config_toml"].replace("\n", "\n    "))
                print(f"  then: {cfg['codex']['env']}")
            elif a["tool"] == "gemini_cli":
                print("  Add to ~/.gemini/settings.json:")
                print("    " + cfg["gemini_cli"]["settings_json"].replace("\n", "\n    "))
            print()
    print("Ready-made agent folders (tokens included, gitignored):")
    print("  Claude Code: cd .baton/agents/claude && claude")
    print("  Codex:       cd .baton/agents/codex && source env.sh && codex   (after adding codex-config.toml to ~/.codex/config.toml)")
    print("  Gemini CLI:  cd .baton/agents/gemini && gemini")
    print()
    print(f"MCP URL: {url}   (set BATON_PUBLIC_URL in .env to your LAN IP for teammates)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--if-empty", action="store_true", help="seed only if there are no rooms yet")
    p.add_argument("--print", action="store_true", help="print connection info and exit")
    args = p.parse_args()
    if args.print:
        print_info()
        return
    with SessionLocal() as db:
        rooms = db.execute(select(func.count()).select_from(Room)).scalar_one()
    if args.if_empty and rooms:
        print(f"Database already has {rooms} room(s); not seeding. (./reset-demo.sh wipes and re-seeds.)")
        return
    demo = seed()
    print(f"Seeded \"{demo['room_name']}\" with invite code {demo['invite_code']}.")


if __name__ == "__main__":
    main()
