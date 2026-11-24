"""Gemini via the Generative Language REST API."""

from __future__ import annotations

import httpx

from app.llm.base import Completion, LLMError, ProviderConfig, ProviderInfo, friendly_http_error

_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    info = ProviderInfo(
        id="gemini",
        label="Gemini (Google)",
        kind="api",
        default_model="gemini-2.5-pro",
        help="Create a key at aistudio.google.com → Get API key.",
        key_env=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        suggested_models=("gemini-2.5-pro", "gemini-2.5-flash"),
    )

    def _base(self, cfg: ProviderConfig) -> str:
        return (cfg.base_url or _BASE).rstrip("/")

    def _headers(self, cfg: ProviderConfig) -> dict:
        return {"x-goog-api-key": cfg.api_key, "Content-Type": "application/json"}

    def complete(self, cfg: ProviderConfig, system: str, user: str, max_tokens: int = 16000) -> Completion:
        model = cfg.model.removeprefix("models/")
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        try:
            r = httpx.post(f"{self._base(cfg)}/models/{model}:generateContent", headers=self._headers(cfg), json=body, timeout=300.0)
        except httpx.HTTPError:
            raise LLMError("Couldn't reach Google. Check your internet connection.") from None
        if r.status_code != 200:
            raise friendly_http_error("Gemini", r.status_code, r.text)
        try:
            data = r.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (ValueError, KeyError, IndexError):
            reason = (data.get("promptFeedback") or {}).get("blockReason") if isinstance(data, dict) else None
            raise LLMError(f"Gemini returned no answer{f' (blocked: {reason})' if reason else ''}.") from None
        if not text.strip():
            raise LLMError("Gemini returned an empty answer (try another model).")
        meta = data.get("usageMetadata") or {}
        return Completion(text=text, input_tokens=meta.get("promptTokenCount"), output_tokens=meta.get("candidatesTokenCount"), model=model)

    def list_models(self, cfg: ProviderConfig) -> list[str]:
        try:
            r = httpx.get(f"{self._base(cfg)}/models", headers=self._headers(cfg), params={"pageSize": 200}, timeout=30.0)
        except httpx.HTTPError:
            raise LLMError("Couldn't reach Google. Check your internet connection.") from None
        if r.status_code != 200:
            raise friendly_http_error("Gemini", r.status_code, r.text)
        out = []
        for m in r.json().get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                out.append(m["name"].removeprefix("models/"))
        return sorted(out)
