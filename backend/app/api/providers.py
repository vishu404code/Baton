"""AI model settings: which providers (Claude, ChatGPT, DeepSeek, Gemini) have a key, which model each uses."""

from fastapi import APIRouter, Depends

from app.auth import current_user_ro
from app.llm import registry, store
from app.llm.base import LLMError, ProviderInfo
from app.models import User
from app.schemas import _In

router = APIRouter(prefix="/api/providers", tags=["providers"])


class ProviderUpdateIn(_In):
    api_key: str | None = None  # "" removes the saved key
    model: str | None = None
    base_url: str | None = None


def provider_out(info: ProviderInfo) -> dict:
    cfg = store.get(info)
    has_key = bool(cfg["api_key"])
    return {
        "id": info.id,
        "label": info.label,
        "kind": info.kind,
        "needs_key": info.needs_key,
        "help": info.help,
        "default_model": info.default_model,
        "model": cfg["model"],
        "has_key": has_key,
        "key_hint": store.hint(cfg["api_key"]),
        "key_source": cfg["key_source"],
        "ready": has_key or not info.needs_key,
        "models": cfg["models"] or list(info.suggested_models),
        "base_url": cfg["base_url"],
    }


@router.get("")
def list_providers(user: User = Depends(current_user_ro)) -> dict:
    return {
        "providers": [provider_out(p.info) for p in registry.PROVIDERS.values()],
        "connect": [
            {"id": t.id, "label": t.label, "kind": t.kind, "help": t.help} for t in registry.MCP_TOOLS
        ],
    }


@router.put("/{provider_id}")
def update_provider(provider_id: str, body: ProviderUpdateIn, user: User = Depends(current_user_ro)) -> dict:
    info = _info(provider_id)
    store.update(info, api_key=body.api_key, model=body.model, base_url=body.base_url)
    if body.api_key is not None:
        store.update(info, models=[])  # a new key can see different models
    return provider_out(info)


@router.post("/{provider_id}/test")
def test_provider(provider_id: str, user: User = Depends(current_user_ro)) -> dict:
    """Check the key by asking the provider which models it can use."""
    info = _info(provider_id)
    provider = registry.PROVIDERS[provider_id]
    cfg = store.config(info)
    if info.needs_key and not cfg.api_key:
        return {"ok": False, "error": f"No API key set for {info.label}.", "provider": provider_out(info)}
    try:
        models = provider.list_models(cfg)
    except LLMError as e:
        return {"ok": False, "error": str(e), "provider": provider_out(info)}
    store.update(info, models=models)
    if models and cfg.model not in models:
        store.update(info, model=models[0])
    return {"ok": True, "models": models, "provider": provider_out(info)}


def _info(provider_id: str) -> ProviderInfo:
    p = registry.PROVIDERS.get(provider_id)
    if p is None:
        from app.errors import not_found

        raise not_found(f"Unknown provider '{provider_id}'.")
    return p.info
