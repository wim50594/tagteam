"""
Central settings – all values sourced from environment variables.
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
    redis_url: str | None = None
    cache_ttl_seconds: int = 300

    jwt_algorithm: str = "HS256"

    # Access token: short-lived, sent in the response body, stored by the
    # frontend (localStorage) and attached as an Authorization header.
    jwt_expire_minutes: int = 15

    # Refresh token: long-lived, sent ONLY as an httpOnly cookie (never
    # exposed to JS / never in a JSON response). Used solely to mint new
    # access tokens via POST /api/auth/refresh.
    refresh_token_expire_days: int = 7
    refresh_cookie_name: str = "tt_refresh"

    # Whether the refresh cookie requires HTTPS (Secure flag). Disable for
    # local HTTP-only development; always enable in production.
    cookie_secure: bool = True

    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    media_dir: str = "data/media"

    # App version, baked into the image at build time from the release's
    # git tag (see Dockerfile ARG/ENV and .github/workflows/release.yml).
    # "dev" is the default for local/dev runs where no tag applies.
    app_version: str = "dev"

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
