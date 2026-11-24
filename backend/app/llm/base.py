from __future__ import annotations

from dataclasses import dataclass, field


class LLMError(Exception):
    """A provider call failed. The message is written for the person using the app."""


@dataclass
class ProviderInfo:
    id: str
    label: str
    kind: str  # "api" (needs a key), "offline" (no key), "mcp" (connects through MCP, no API)
    default_model: str
    help: str
    needs_key: bool = True
    key_env: tuple[str, ...] = ()
    suggested_models: tuple[str, ...] = ()


@dataclass
class Completion:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ProviderConfig:
    api_key: str
    model: str
    base_url: str | None = None


def friendly_http_error(provider: str, status: int, body: str) -> LLMError:
    detail = (body or "").strip().replace("\n", " ")[:240]
    if status in (401, 403):
        return LLMError(f"{provider} rejected the API key (HTTP {status}). Check the key in Settings → AI models.")
    if status == 404:
        return LLMError(f"{provider} doesn't know that model (HTTP 404). Pick another model. {detail}")
    if status == 429:
        return LLMError(f"{provider} rate limit or quota reached (HTTP 429). Wait a bit or check billing. {detail}")
    if status >= 500:
        return LLMError(f"{provider} is having problems (HTTP {status}). Try again shortly.")
    return LLMError(f"{provider} returned HTTP {status}: {detail}")
