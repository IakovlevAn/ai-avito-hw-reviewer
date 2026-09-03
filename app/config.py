from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Avito AI Reviewer"
    database_url: str = "sqlite:///./data/ai_reviewer.db"
    github_token: str | None = None
    github_timeout_seconds: float = 20.0
    github_max_files: int = 120
    github_max_file_bytes: int = 100_000
    github_max_total_bytes: int = 800_000
    telegram_bot_token: str | None = None
    telegram_default_chat_id: str | None = None
    review_due_hours: int = 48
    web_dist_dir: Path = Path("web/dist")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
