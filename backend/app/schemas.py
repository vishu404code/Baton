"""Request bodies (Pydantic v2). Responses are built in app/serializers.py to match the contract exactly."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SessionIn(_In):
    display_name: str = Field(min_length=1, max_length=40)


class RoomCreateIn(_In):
    name: str = Field(min_length=1, max_length=80)


class JoinIn(_In):
    invite_code: str = Field(min_length=1, max_length=32)


class ChecksIn(_In):
    citations_present: bool | None = None
    sources_exist: bool | None = None
    content_schema: bool | None = None


class SettingsIn(_In):
    checks: ChecksIn | None = None
    min_sources: int | None = Field(default=None, ge=0, le=10)
    lease_minutes: int | None = Field(default=None, ge=1, le=120)
    require_approval: bool | None = None


class MemberRoleIn(_In):
    role: Literal["member", "mentor"]


class AgentCreateIn(_In):
    name: str = Field(min_length=1, max_length=60)
    tool: Literal["claude_code", "codex", "gemini_cli", "cursor", "other"]
    role: Literal["planner", "reviewer", "observer"]

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v
