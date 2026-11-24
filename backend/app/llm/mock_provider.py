"""An offline demo model: needs no key and no internet. It writes a real, rule-following answer
from the project record it is given, so the whole app (claims, checks, stale flags, approvals)
can be tried before any API key is added."""

from __future__ import annotations

import json

from app.llm.base import Completion, ProviderConfig, ProviderInfo


class MockProvider:
    info = ProviderInfo(
        id="mock",
        label="Demo model (offline)",
        kind="offline",
        default_model="demo-1",
        help="Runs on this computer with no key. It follows the project's decisions but is not a real AI.",
        needs_key=False,
        suggested_models=("demo-1",),
    )

    def complete(self, cfg: ProviderConfig, system: str, user: str, max_tokens: int = 16000) -> Completion:
        try:
            ctx = json.loads(user.split("PROJECT RECORD (JSON):", 1)[1].split("\n\nREPLY FORMAT:", 1)[0])
        except Exception:
            ctx = {}
        decisions = ctx.get("decisions", [])
        sources = ctx.get("sources", [])
        task = ctx.get("task", {})
        if ctx.get("role") == "reviewer":
            draft = (ctx.get("under_review") or {}).get("body", "")
            problems = [d for d in decisions if d.get("label") and d["label"].split()[-1] and d["label"] not in draft and d["label"].lower() not in draft.lower()]
            comments = "Checked the draft against " + (", ".join(d["label"] for d in decisions) or "the brief") + ". "
            comments += "It follows the recorded decisions." if not problems else "It does not mention " + ", ".join(d["label"] for d in problems) + "."
            out = {"verdict": "approve", "comments": comments}
        else:
            lines = [f"## {task.get('title', 'Plan')}", "", ctx.get("brief", {}).get("title", ""), ""]
            for d in decisions:
                lines.append(f"- **{d['label']}** ({d['title']}): {d['statement']}")
            if sources:
                lines += ["", "Based on: " + ", ".join(s["label"] for s in sources[:3])]
            out = {"title": task.get("title", "Plan"), "body": "\n".join(lines).strip(), "sources": [s["label"] for s in sources[:1]]}
        return Completion(text=json.dumps(out), model=cfg.model or "demo-1")

    def list_models(self, cfg: ProviderConfig) -> list[str]:
        return ["demo-1"]
