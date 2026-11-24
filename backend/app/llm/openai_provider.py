"""ChatGPT (OpenAI) and DeepSeek: both speak the OpenAI chat-completions format."""

from __future__ import annotations

import httpx

from app.llm.base import Completion, LLMError, ProviderConfig, ProviderInfo, friendly_http_error

_SKIP = ("embedding", "whisper", "tts", "dall-e", "moderation", "audio", "realtime", "image", "transcribe", "search")


class ChatCompletionsProvider:
    def __init__(self, info: ProviderInfo, base_url: str, token_param: str, label: str):
        self.info = info
        self.base_url = base_url.rstrip("/")
        self.token_param = token_param
        self.label = label

    def _headers(self, cfg: ProviderConfig) -> dict:
        return {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}

    def _base(self, cfg: ProviderConfig) -> str:
        return (cfg.base_url or self.base_url).rstrip("/")

    def complete(self, cfg: ProviderConfig, system: str, user: str, max_tokens: int = 16000) -> Completion:
        body = {
            "model": cfg.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            self.token_param: max_tokens,
        }
        try:
            r = httpx.post(f"{self._base(cfg)}/chat/completions", headers=self._headers(cfg), json=body, timeout=300.0)
        except httpx.HTTPError:
            raise LLMError(f"Couldn't reach {self.label}. Check your internet connection.") from None
        if r.status_code != 200:
            raise friendly_http_error(self.label, r.status_code, r.text)
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError):
            raise LLMError(f"{self.label} sent an answer in an unexpected format.") from None
        if not text.strip():
            raise LLMError(f"{self.label} returned an empty answer (try another model).")
        usage = data.get("usage") or {}
        return Completion(
            text=text,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            model=data.get("model", cfg.model),
        )

    def list_models(self, cfg: ProviderConfig) -> list[str]:
        try:
            r = httpx.get(f"{self._base(cfg)}/models", headers=self._headers(cfg), timeout=30.0)
        except httpx.HTTPError:
            raise LLMError(f"Couldn't reach {self.label}. Check your internet connection.") from None
        if r.status_code != 200:
            raise friendly_http_error(self.label, r.status_code, r.text)
        ids = [m.get("id", "") for m in r.json().get("data", [])]
        return sorted(i for i in ids if i and not any(s in i.lower() for s in _SKIP))


OPENAI = ChatCompletionsProvider(
    ProviderInfo(
        id="openai",
        label="ChatGPT (OpenAI)",
        kind="api",
        default_model="gpt-5",
        help="Create a key at platform.openai.com → API keys. Use 'Test' to list the models your key can use.",
        key_env=("OPENAI_API_KEY",),
        suggested_models=("gpt-5", "gpt-4.1", "gpt-4o"),
    ),
    base_url="https://api.openai.com/v1",
    token_param="max_completion_tokens",
    label="ChatGPT (OpenAI)",
)

DEEPSEEK = ChatCompletionsProvider(
    ProviderInfo(
        id="deepseek",
        label="DeepSeek",
        kind="api",
        default_model="deepseek-chat",
        help="Create a key at platform.deepseek.com → API keys.",
        key_env=("DEEPSEEK_API_KEY",),
        suggested_models=("deepseek-chat", "deepseek-reasoner"),
    ),
    base_url="https://api.deepseek.com",
    token_param="max_tokens",
    label="DeepSeek",
)
