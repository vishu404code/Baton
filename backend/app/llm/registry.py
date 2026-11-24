from __future__ import annotations

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import ProviderInfo
from app.llm.gemini_provider import GeminiProvider
from app.llm.mock_provider import MockProvider
from app.llm.openai_provider import DEEPSEEK, OPENAI

PROVIDERS = {p.info.id: p for p in (AnthropicProvider(), OPENAI, DEEPSEEK, GeminiProvider(), MockProvider())}

# Tools that connect through MCP instead of an API key. They appear in the UI as "connect" cards.
MCP_TOOLS = [
    ProviderInfo("antigravity", "Antigravity", "mcp", "", "Add Baton as an MCP server in Antigravity; it then works tasks itself.", needs_key=False),
    ProviderInfo("claude_code", "Claude Code (CLI)", "mcp", "", "Run Claude Code with Baton's MCP config.", needs_key=False),
    ProviderInfo("codex", "Codex (CLI)", "mcp", "", "Run Codex with Baton's MCP config.", needs_key=False),
    ProviderInfo("gemini_cli", "Gemini CLI", "mcp", "", "Run Gemini CLI with Baton's MCP config.", needs_key=False),
]

# How each provider's agents are shown in the UI (icon and colour come from the tool type).
TOOL_FOR_PROVIDER = {"anthropic": "claude_code", "openai": "codex", "gemini": "gemini_cli", "deepseek": "other", "mock": "other"}


def get(provider_id: str):
    p = PROVIDERS.get(provider_id)
    if p is None:
        from app.llm.base import LLMError

        raise LLMError(f"Unknown AI provider '{provider_id}'.")
    return p
