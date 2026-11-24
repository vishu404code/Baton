"""Milestone 3: the MCP server over real Streamable HTTP, as Claude Code and Codex would use it."""

import json

import anyio
import httpx
import pytest


async def _call(url: str, token: str | None, tool: str, args: dict | None = None):
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with Client(streamable_http_client(f"{url}/mcp", http_client=http)) as client:
            return await client.call_tool(tool, args or {})


def call(url, token, tool, args=None):
    """Return (is_error, data) for one tool call."""
    res = anyio.run(_call, url, token, tool, args)
    if res.is_error:
        return True, " ".join(getattr(c, "text", "") for c in res.content)
    data = res.structured_content
    if data is None:
        data = json.loads(res.content[0].text)
    return False, data.get("result", data) if isinstance(data, dict) and set(data) == {"result"} else data


def test_mcp_rejects_missing_or_bad_tokens(live_server):
    r = httpx.post(f"{live_server}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    r = httpx.post(f"{live_server}/mcp", json={}, headers={"Authorization": "Bearer bat_nope"})
    assert r.status_code == 401


def test_tool_list_and_instructions(world, live_server):
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    async def go():
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {world.claude['token']}"}) as http:
            async with Client(streamable_http_client(f"{live_server}/mcp", http_client=http)) as c:
                tools = await c.list_tools()
                return sorted(t.name for t in tools.tools), c.instructions

    names, instructions = anyio.run(go)
    assert names == sorted([
        "get_room_context", "list_tasks", "read_record", "claim_task", "heartbeat",
        "submit_result", "release_task", "add_source", "comment",
    ])
    assert "get_room_context first" in (instructions or "")


def test_full_task_and_handoff_over_mcp(world, live_server, client):
    """Claude Code drafts the plan; Codex reviews it, recovering everything from Baton alone."""
    url, ct, xt = live_server, world.claude["token"], world.codex["token"]

    err, ctx = call(url, ct, "get_room_context")
    assert not err, ctx
    assert ctx["me"]["role"] == "planner" and ctx["brief"]["label"] == "Brief 1"
    assert [d["label"] for d in ctx["decisions"]] == ["Decision 1", "Decision 2", "Decision 3"]

    err, tasks = call(url, ct, "list_tasks")
    assert tasks["claimable_by_you"] == ["Task 1"]

    err, msg = call(url, xt, "claim_task", {"task_id": "Task 1"})
    assert err and "needs a planner" in msg

    err, claimed = call(url, ct, "claim_task", {"task_id": "Task 1"})
    assert not err, claimed
    assert claimed["inputs"]["decisions"][1]["content"]["statement"] == "We launch on 10 January."

    err, src = call(url, ct, "add_source", {"title": "Venue booking", "url_or_text": "Main hall booked for 10 Jan."})
    assert src["label"] == "Source 3"

    based_on = [ctx["brief"]["revision_id"]] + [d["revision_id"] for d in ctx["decisions"]]
    err, out = call(url, ct, "submit_result", {
        "task_id": "Task 1",
        "content": {"body": "## Launch plan\n1. Launch 10 January in the main hall."},
        "based_on": based_on,
        "sources": [ctx["sources"][0]["source_id"], src["source_id"]],
        "idempotency_key": "claude-task1-1",
    })
    assert not err and out["status"] == "completed", out
    assert len(out["checks"]) == 7 and out["result"]["label"] == "Draft 1"

    # Retry with the same key: same result, applied once.
    err, again = call(url, ct, "submit_result", {
        "task_id": "Task 1", "content": {"body": "x"}, "based_on": based_on, "sources": [], "idempotency_key": "claude-task1-1",
    })
    assert again["submission_id"] == out["submission_id"] and again["attempts"] == 2

    # The handoff: Codex sees the draft, its based_on links and sources without any chat history.
    err, claimed2 = call(url, xt, "claim_task", {"task_id": "Task 2"})
    assert not err, claimed2
    under = claimed2["inputs"]["under_review"]
    assert under["label"] == "Draft 1" and "main hall" in under["content"]["body"]
    assert {b["label"] for b in under["based_on"]} == {"Brief 1", "Decision 1", "Decision 2", "Decision 3"}
    assert {s["label"] for s in under["sources"]} == {"Source 1", "Source 3"}

    err, _ = call(url, xt, "comment", {"record_id": "Draft 1", "text": "Dates match Decision 2."})
    assert not err
    err, review = call(url, xt, "submit_result", {
        "task_id": "Task 2",
        "content": {"verdict": "approve", "comments": "Plan follows the brief and all three decisions."},
        "based_on": based_on + [under["revision_id"]],
        "idempotency_key": "codex-task2-1",
    })
    assert not err and review["status"] == "completed", review
    assert review["result"]["label"] == "Review 2"

    err, rec = call(url, xt, "read_record", {"record_id": "Draft 1"})
    assert rec["comments"][0]["author"] == "Ben's Codex"

    # The UI sees it all: agents online, both outputs on the board.
    agents = client.get(f"/api/rooms/{world.room_id}/agents", headers=world.asha["h"]).json()["agents"]
    assert all(a["online"] for a in agents)
    board = client.get(f"/api/rooms/{world.room_id}/board", headers=world.asha["h"]).json()["tasks"]
    assert [(t["task"]["label"], t["output"]["label"]) for t in board] == [("Task 1", "Draft 1"), ("Task 2", "Review 2")]
    types = [e["type"] for e in client.get(f"/api/rooms/{world.room_id}/events?limit=500", headers=world.asha["h"]).json()["events"]]
    assert types.count("agent.connected") == 2 and types.count("submission.duplicate") == 1


def test_stale_error_over_mcp(world, live_server, client):
    url, ct = live_server, world.claude["token"]
    _, ctx = call(url, ct, "get_room_context")
    call(url, ct, "claim_task", {"task_id": "Task 1"})
    client.post(f"/api/records/{world.dec2['record']['id']}/revisions", json={"content": {"statement": "15 January."}}, headers=world.asha["h"])
    err, out = call(url, ct, "submit_result", {
        "task_id": "Task 1", "content": {"body": "plan"},
        "based_on": [ctx["brief"]["revision_id"]] + [d["revision_id"] for d in ctx["decisions"]],
        "sources": [ctx["sources"][0]["source_id"]], "idempotency_key": "s1",
    })
    assert not err and out["ok"] is False
    assert out["message"].startswith("Rejected by revisions_current: stale: based on Decision 2 v1, now v2")
