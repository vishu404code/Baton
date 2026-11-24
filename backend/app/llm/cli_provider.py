"""Run an AI through the app already installed and signed in on this computer (no API key).

Claude Code, Codex (inside the ChatGPT app) and the Antigravity CLI can all answer one prompt non-interactively with the
user's own login. Baton gives them the shared memory in the prompt and tells them not to use tools, so every
answer comes back as plain text that Baton then saves."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.llm.base import Completion, LLMError, ProviderConfig

TIMEOUT = 240


def _first_existing(*paths: str) -> str | None:
    for p in paths:
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def find_claude() -> str | None:
    hits = sorted(glob.glob(str(Path.home() / "Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")))
    return shutil.which("claude") or (hits[-1] if hits else None)


def find_codex() -> str | None:
    return shutil.which("codex") or _first_existing("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")


def find_agy() -> str | None:
    return shutil.which("agy") or _first_existing(str(Path.home() / ".gemini/bin/agy"))


def _no_tools(prompt: str) -> str:
    return prompt + "\n\n(Answer in plain text only. Do not call any tools or read any files: Baton already supplied everything you need.)"


@dataclass
class CliSeat:
    id: str  # same id as the API provider it stands in for ("anthropic", "openai", "gemini", "antigravity")
    label: str
    model_label: str
    finder: object

    def path(self) -> str | None:
        if os.environ.get("BATON_DISABLE_CLI"):
            return None
        return self.finder()

    def available(self) -> bool:
        return self.path() is not None

    def complete(self, cfg: ProviderConfig, system: str, user: str, max_tokens: int = 0) -> Completion:
        exe = self.path()
        if not exe:
            raise LLMError(f"{self.label} isn't installed on this computer. Add an API key under Tools & keys instead.")
        prompt = _no_tools(system + "\n\n---\n\n" + user)
        with tempfile.TemporaryDirectory(prefix="baton-chat-") as cwd:
            try:
                text = self._run(exe, prompt, cwd)
            except subprocess.TimeoutExpired:
                raise LLMError(f"{self.label} took too long to answer. Try again.") from None
            except OSError as e:
                raise LLMError(f"Couldn't start {self.label}: {e}") from None
        if not text.strip():
            raise LLMError(f"{self.label} returned no answer. Open the {self.label} app once to make sure you're signed in, then try again.")
        return Completion(text=text.strip(), model=self.model_label)

    def _run(self, exe: str, prompt: str, cwd: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError


class _Claude(CliSeat):
    def _run(self, exe, prompt, cwd):
        r = subprocess.run([exe, "-p", "--strict-mcp-config", "--tools", ""], input=prompt, capture_output=True, text=True, cwd=cwd, timeout=TIMEOUT)
        if r.returncode != 0 and not r.stdout.strip():
            raise LLMError(f"Claude Code said: {(r.stderr or r.stdout).strip()[:240] or 'it could not answer'}. Make sure you're signed in to Claude.")
        return r.stdout


class _Codex(CliSeat):
    def _run(self, exe, prompt, cwd):
        out = os.path.join(cwd, "answer.txt")
        r = subprocess.run([exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-c", "mcp_servers.baton.enabled=false", "-o", out, "-"],
                           input=prompt, capture_output=True, text=True, cwd=cwd, timeout=TIMEOUT)
        try:
            text = Path(out).read_text()
        except OSError:
            text = ""
        if not text.strip() and r.returncode != 0:
            raise LLMError(f"Codex said: {(r.stderr or r.stdout).strip()[-240:] or 'it could not answer'}. Make sure you're signed in to ChatGPT.")
        return text


class _Agy(CliSeat):
    model: str | None = None

    def _run(self, exe, prompt, cwd):
        cmd = [exe, "-p", prompt, "--print-timeout", f"{TIMEOUT - 10}s"]
        if self.model:
            cmd += ["--model", self.model]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=TIMEOUT)
        if r.returncode != 0 and not r.stdout.strip():
            raise LLMError(f"Antigravity said: {(r.stderr or r.stdout).strip()[-240:] or 'it could not answer'}. Make sure you're signed in to Antigravity.")
        return r.stdout


def _agy(id_, label, model_label, model):
    s = _Agy(id_, label, model_label, find_agy)
    s.model = model
    return s


CLI_SEATS: dict[str, CliSeat] = {
    "anthropic": _Claude("anthropic", "Claude", "Claude Code", find_claude),
    "openai": _Codex("openai", "ChatGPT", "Codex", find_codex),
    "gemini": _agy("gemini", "Gemini", "Gemini 3.8 Flash via Antigravity", "gemini-3.8-flash-medium"),
    "antigravity": _agy("antigravity", "Antigravity", "Antigravity agent", None),
}
