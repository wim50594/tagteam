"""
Central settings – all values sourced from environment variables.
Never import secrets directly; always use this module.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    admin_password: str
    jwt_secret: str
    admin_username: str = "admin"

    # Primary relational database (PostgreSQL, SQLite, ...)
    database_url: str = "sqlite+aiosqlite:///./data/tagteam.db"

    # Redis is optional and used only as a cache. If unset, caching is
    # simply skipped and everything falls back to the RDBMS.
    redis_url: str | None = "redis://redis:6379"
    cache_ttl_seconds: int = 300

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    media_dir: str = "/app/data/media"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def media_path(self) -> Path:
        p = Path(self.media_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings.model_validate({})
