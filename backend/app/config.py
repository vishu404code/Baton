from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite file lives here: <data dir>/baton.db (the desktop app sets this to its user-data folder).
    baton_data_dir: str = "./data"

    baton_public_url: str = "http://localhost:8000"
    baton_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    baton_default_lease_minutes: int = 15
    baton_default_min_sources: int = 1
    baton_default_require_approval: bool = True
    baton_agent_online_seconds: int = 120
    baton_lease_sweep_seconds: int = 10
    # Pause between verification checks so the room can watch them tick (demo polish).
    baton_check_delay_ms: int = 0

    log_level: str = "info"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.baton_cors_origins.split(",") if o.strip()]

    @property
    def mcp_url(self) -> str:
        return self.baton_public_url.rstrip("/") + "/mcp"


@lru_cache
def get_settings() -> Settings:
    return Settings()
