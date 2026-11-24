"""Where provider settings (API keys, chosen models) are kept: one JSON file, mode 600, on this computer.

Keys are never returned by the API (only whether one is set and its last 4 characters) and never logged.
Environment variables (ANTHROPIC_API_KEY, OPENAI_API_KEY, ...) are used as a fallback.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from app.db import data_dir
from app.llm.base import ProviderConfig, ProviderInfo

_lock = threading.Lock()


def _path() -> Path:
    override = os.environ.get("BATON_PROVIDER_KEYS_FILE")
    return Path(override) if override else data_dir() / "providers.json"


def _read() -> dict:
    p = _path()
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def _env_key(info: ProviderInfo) -> str:
    for name in info.key_env:
        if os.environ.get(name):
            return os.environ[name]
    return ""


def get(info: ProviderInfo) -> dict:
    with _lock:
        saved = _read().get(info.id, {})
    key = saved.get("api_key") or _env_key(info)
    return {
        "api_key": key,
        "model": saved.get("model") or info.default_model,
        "base_url": saved.get("base_url") or None,
        "models": saved.get("models") or [],
        "key_source": "saved" if saved.get("api_key") else ("environment" if key else None),
    }


def config(info: ProviderInfo) -> ProviderConfig:
    c = get(info)
    return ProviderConfig(api_key=c["api_key"], model=c["model"], base_url=c["base_url"])


def update(info: ProviderInfo, *, api_key: str | None = None, model: str | None = None,
           base_url: str | None = None, models: list[str] | None = None) -> None:
    with _lock:
        data = _read()
        cur = data.get(info.id, {})
        if api_key is not None:
            if api_key.strip():
                cur["api_key"] = api_key.strip()
            else:
                cur.pop("api_key", None)
        if model is not None:
            cur["model"] = model.strip() or info.default_model
        if base_url is not None:
            if base_url.strip():
                cur["base_url"] = base_url.strip()
            else:
                cur.pop("base_url", None)
        if models is not None:
            cur["models"] = models
        data[info.id] = cur
        _write(data)


def hint(key: str) -> str | None:
    return f"…{key[-4:]}" if len(key) >= 8 else ("set" if key else None)
