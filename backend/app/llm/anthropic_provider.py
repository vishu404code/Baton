"""Claude via the official Anthropic SDK."""

from __future__ import annotations

import anthropic

from app.llm.base import Completion, LLMError, ProviderConfig, ProviderInfo

# Models that support the server-side refusal fallback (route a declined request to another model).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2"}


class AnthropicProvider:
    info = ProviderInfo(
        id="anthropic",
        label="Claude (Anthropic)",
        kind="api",
        default_model="claude-opus-5-5",
        help="Create a key at console.anthropic.com → API keys.",
        key_env=("ANTHROPIC_API_KEY",),
        suggested_models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
    )

    def _client(self, cfg: ProviderConfig) -> anthropic.Anthropic:
        kwargs = {"api_key": cfg.api_key, "timeout": 300.0, "max_retries": 2}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        return anthropic.Anthropic(**kwargs)

    def complete(self, cfg: ProviderConfig, system: str, user: str, max_tokens: int = 16000) -> Completion:
        client = self._client(cfg)
        kwargs = dict(
            model=cfg.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        try:
            if cfg.model in _FALLBACK_MODELS:
                try:
                    # A safety decline is re-run on a fallback model inside the same call.
                    resp = client.beta.messages.create(
                        betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                    )
                except anthropic.BadRequestError as e:
                    if "fallback" not in str(e).lower():
                        raise
                    resp = client.messages.create(**kwargs)  # endpoint without the beta
            else:
                resp = client.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            raise LLMError("Claude rejected the API key. Check it in Settings → AI models.") from None
        except anthropic.NotFoundError:
            raise LLMError(f"Claude doesn't know the model '{cfg.model}'. Pick another model.") from None
        except anthropic.RateLimitError:
            raise LLMError("Claude rate limit or quota reached. Wait a bit or check billing.") from None
        except anthropic.APIConnectionError:
            raise LLMError("Couldn't reach Anthropic. Check your internet connection.") from None
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude returned HTTP {e.status_code}: {str(e)[:240]}") from None

        if resp.stop_reason == "refusal":
            detail = getattr(getattr(resp, "stop_details", None), "explanation", None) or "no explanation given"
            raise LLMError(f"Claude declined this request ({detail}).")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        if not text.strip():
            raise LLMError("Claude returned an empty answer (try a larger token limit or another model).")
        return Completion(
            text=text,
            input_tokens=getattr(resp.usage, "input_tokens", None),
            output_tokens=getattr(resp.usage, "output_tokens", None),
            model=getattr(resp, "model", cfg.model),
        )

    def list_models(self, cfg: ProviderConfig) -> list[str]:
        client = self._client(cfg)
        try:
            return [m.id for m in client.models.list(limit=100)]
        except anthropic.AuthenticationError:
            raise LLMError("Claude rejected the API key.") from None
        except anthropic.APIConnectionError:
            raise LLMError("Couldn't reach Anthropic. Check your internet connection.") from None
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude returned HTTP {e.status_code}: {str(e)[:200]}") from None
