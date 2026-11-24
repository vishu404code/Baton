"""Knowledge base: reference material (a website's articles, places, itineraries...) that every AI reads.

Nothing is "trained": the right documents are found for each question and placed in front of the model together with
the shared memory. That is how an AI app learns a specific site without a fine-tuned model, and it works the same for
Claude, ChatGPT, Gemini and Antigravity."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import delete, func, select

from app.models import KnowledgeDoc

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "jaipur_journals.json"
SKIP_KEYS = {"id", "slug", "color", "cover", "image", "lat", "lng", "featured", "sample", "website", "short"}
KIND_OF = {"articles": "article", "places": "place", "itineraries": "itinerary", "hotels": "hotel", "people": "person", "categories": "section"}
STOP = set("a an the and or of to in on for with is are was were be it this that at by from as how what which who where when do does can i you we my your our me about please tell give show make".split())

GUIDELINES = """You are the assistant for The Jaipur Journals, an online magazine about Jaipur, India (the Pink City): forts, food, crafts, bazaars, stays and trip planning.
How to answer:
- Use the knowledge documents provided. Quote real names, places, times, prices and tips from them. Mention the article or place by title when it helps.
- Never say you cannot access the website. Its content is included below. If something is not covered, say so briefly and then give your best general Jaipur advice, marked as general.
- Be concrete and practical: a short plan, times, rough costs in rupees, one tip. Keep answers focused (under about 250 words unless asked for more).
- When another assistant already answered earlier in this conversation, continue from it and stay consistent with its numbers and choices."""


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and (len(w) > 1 or w.isdigit())]


def flatten(obj, depth: int = 0) -> str:
    """Turn any JSON value into readable text (skips colours, ids, image paths)."""
    pad = "  " * depth
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            if k in SKIP_KEYS or v in ("", None, [], {}):
                continue
            label = re.sub(r"(?<!^)(?=[A-Z])", " ", str(k)).replace("_", " ").capitalize()
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{label}:")
                lines.append(flatten(v, depth + 1))
            else:
                lines.append(f"{pad}{label}: {v}")
        return "\n".join(l for l in lines if l)
    if isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            return pad + ("\n" + pad).join(f"- {x}" for x in obj) if depth else "\n\n".join(str(x) for x in obj)
        return "\n".join(flatten(x, depth) + ("\n" if isinstance(x, dict) else "") for x in obj)
    return f"{pad}{obj}"


def docs_from_collections(source: str, url: str | None, cols: dict) -> list[dict]:
    docs = []
    for name, items in cols.items():
        if not isinstance(items, list):
            continue
        kind = KIND_OF.get(name, name.rstrip("s") or "page")
        for it in items:
            if not isinstance(it, dict):
                continue
            title = it.get("title") or it.get("name") or it.get("slug") or it.get("id") or kind
            tags = ", ".join(map(str, [it.get("category"), *(it.get("tags") or []), it.get("type"), it.get("role")] )).replace("None, ", "").replace(", None", "")
            docs.append({"source": source, "source_url": url, "kind": kind, "title": str(title)[:200], "tags": tags[:400], "text": flatten(it).strip()})
    return docs


def _page_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg|head).*?</\1>", " ", html)
    html = re.sub(r"(?s)<!--.*?-->", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|section|article)>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return "\n".join(" ".join(l.split()) for l in text.splitlines() if l.strip())


def _embedded_json(js: str):
    """Find `window.X = {...};` style data in a script and parse it."""
    m = re.search(r"=\s*(\{)", js)
    if not m:
        return None
    start, depth, in_str, esc = m.start(1), 0, False, False
    for i in range(start, len(js)):
        c = js[i]
        if in_str:
            esc = (c == "\\" and not esc)
            if c == '"' and not esc:
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(js[start : i + 1])
                except ValueError:
                    return None
    return None


def fetch_site(url: str) -> list[dict]:
    """Read a web page. Sites that ship their content as a data script (like many single-page apps) are read from it."""
    if not re.match(r"^https?://", url):
        raise ValueError("Enter a full web address starting with http:// or https://")
    host = urlparse(url).netloc
    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "Baton/1.0"}) as c:
            r = c.get(url)
            r.raise_for_status()
            html = r.text
            title = unescape((re.search(r"(?is)<title>(.*?)</title>", html) or [None, host])[1]).strip() or host
            docs: list[dict] = []
            for src in re.findall(r'(?i)<script[^>]+src=["\']([^"\']+)["\']', html):
                full = urljoin(url, src)
                if urlparse(full).netloc != host:
                    continue
                try:
                    js = c.get(full).text
                except httpx.HTTPError:
                    continue
                data = _embedded_json(js) if len(js) > 500 else None
                if isinstance(data, dict) and any(isinstance(v, list) and v and isinstance(v[0], dict) for v in data.values()):
                    docs += docs_from_collections(title, url, data)
            if not docs:
                text = _page_text(html)
                if len(text) < 80:
                    raise ValueError("That page has no readable text (it may need a login or build its content in the browser).")
                docs = [{"source": title, "source_url": url, "kind": "page", "title": title[:200], "tags": "", "text": text[:20000]}]
            return docs
    except httpx.HTTPStatusError as e:
        raise ValueError(f"The website answered with an error (HTTP {e.response.status_code}).") from None
    except httpx.HTTPError:
        raise ValueError("Couldn't reach that website. Check the address and your internet connection.") from None


def save_docs(db, docs: list[dict], source_url: str | None = None) -> int:
    if not docs:
        return 0
    cond = KnowledgeDoc.source == docs[0]["source"]
    if docs[0].get("source_url"):
        cond = cond | (KnowledgeDoc.source_url == docs[0]["source_url"])
    db.execute(delete(KnowledgeDoc).where(cond))
    for d in docs:
        db.add(KnowledgeDoc(**d))
    db.flush()
    return len(docs)


def seed_defaults(db) -> None:
    """Ship the Jaipur Journals content in the app so every AI knows it from the first launch (works offline)."""
    if db.execute(select(func.count()).select_from(KnowledgeDoc)).scalar_one():
        return
    snap = json.loads(SEED_FILE.read_text())
    docs = docs_from_collections("The Jaipur Journals", snap["source_url"], snap["collections"])
    docs.insert(0, {"source": "The Jaipur Journals", "source_url": snap["source_url"], "kind": "instructions", "title": "How to answer", "tags": "", "text": GUIDELINES})
    save_docs(db, docs)


def sources(db) -> list[dict]:
    rows = db.execute(select(KnowledgeDoc.source, KnowledgeDoc.source_url, func.count()).group_by(KnowledgeDoc.source, KnowledgeDoc.source_url)).all()
    return [{"source": s, "url": u, "documents": n} for s, u, n in rows]


def remove_source(db, source: str) -> None:
    db.execute(delete(KnowledgeDoc).where(KnowledgeDoc.source == source))


def _all(db) -> list[KnowledgeDoc]:
    return list(db.execute(select(KnowledgeDoc).order_by(KnowledgeDoc.created_at)).scalars())


def search(db, query: str, k: int = 6) -> list[KnowledgeDoc]:
    docs = [d for d in _all(db) if d.kind != "instructions"]
    q = _words(query)
    if not q or not docs:
        return []
    toks = [(d, Counter(_words(d.title)), Counter(_words(d.tags)), Counter(_words(d.text))) for d in docs]
    df = Counter(w for _d, a, b, c in toks for w in set(a) | set(b) | set(c))
    n = len(docs)
    scored = []
    for d, a, b, c in toks:
        s = 0.0
        for w in set(q):
            idf = math.log(1 + n / (1 + df.get(w, 0)))
            s += idf * (3 * a.get(w, 0) + 2 * b.get(w, 0) + min(c.get(w, 0), 4) * 0.7)
        if s > 0:
            scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    return [d for _s, d in scored[:k]]


def index_markdown(db) -> str:
    docs = [d for d in _all(db) if d.kind != "instructions"]
    if not docs:
        return ""
    by_kind: dict[str, list[str]] = {}
    for d in docs:
        by_kind.setdefault(d.kind, []).append(d.title)
    lines = [f"- {kind}s ({len(t)}): " + "; ".join(t) for kind, t in by_kind.items()]
    return "\n".join(lines)


def prompt_block(db, query: str, budget: int = 13000) -> tuple[str, int]:
    """The knowledge part of an AI's prompt: guidelines, a map of everything available, and the best-matching documents."""
    docs = _all(db)
    if not docs:
        return "", 0
    parts = ["## Knowledge base (reference material you must use)"]
    guide = [d for d in docs if d.kind == "instructions"]
    for g in guide:
        parts.append(g.text)
    idx = index_markdown(db)
    if idx:
        parts.append("Everything available (ask for any of it):\n" + idx)
    hits = search(db, query, 8)
    used, count = 0, 0
    for d in hits:
        chunk = f"### {d.title} ({d.kind})\n{d.text}"
        if used + len(chunk) > budget:
            chunk = chunk[: max(0, budget - used)]
        if not chunk.strip():
            break
        parts.append(chunk)
        used += len(chunk)
        count += 1
        if used >= budget:
            break
    return "\n\n".join(parts), count
