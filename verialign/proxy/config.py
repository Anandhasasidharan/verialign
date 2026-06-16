import re
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SQLITE_DEFAULT = "sqlite:///./verialign.sqlite3"


def is_async_database(url: str) -> bool:
    return bool(re.match(r"^(postgresql|mysql|asyncpg)", url, re.IGNORECASE))


class Settings(BaseSettings):
    upstream_base_url: str | None = Field(
        default=None, alias="VERIALIGN_UPSTREAM_BASE_URL"
    )
    upstream_api_key: str | None = Field(
        default=None, alias="VERIALIGN_UPSTREAM_API_KEY"
    )
    upstream_timeout_seconds: float = Field(
        default=60.0, alias="VERIALIGN_UPSTREAM_TIMEOUT_SECONDS"
    )
    db_path: str = Field(default="./verialign.sqlite3", alias="VERIALIGN_DB_PATH")

    database_url: str = Field(default=SQLITE_DEFAULT, alias="VERIALIGN_DATABASE_URL")

    web_search_api_key: str | None = Field(
        default=None, alias="VERIALIGN_WEB_SEARCH_API_KEY"
    )
    web_search_provider: str = Field(
        default="tavily", alias="VERIALIGN_WEB_SEARCH_PROVIDER"
    )

    proxy_api_key: str | None = Field(default=None, alias="VERIALIGN_PROXY_API_KEY")
    require_proxy_auth: bool = Field(
        default=False, alias="VERIALIGN_REQUIRE_PROXY_AUTH"
    )

    rate_limit_requests_per_minute: int = Field(
        default=60, alias="VERIALIGN_RATE_LIMIT_RPM"
    )
    rate_limit_tokens_per_minute: int = Field(
        default=100000, alias="VERIALIGN_RATE_LIMIT_TPM"
    )

    redact_traces: bool = Field(default=True, alias="VERIALIGN_REDACT_TRACES")

    max_request_body_size: int = Field(
        default=10 * 1024 * 1024, alias="VERIALIGN_MAX_REQUEST_BODY_SIZE"
    )

    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["*"], alias="VERIALIGN_CORS_ALLOWED_ORIGINS"
    )

    proxy_timeout_seconds: float = Field(
        default=120.0, alias="VERIALIGN_PROXY_TIMEOUT_SECONDS"
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", populate_by_name=True
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
