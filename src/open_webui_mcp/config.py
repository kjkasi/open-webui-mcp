from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    openwebui_base_url: str = Field(
        default="http://127.0.0.1:3000", validation_alias="OPENWEBUI_BASE_URL"
    )
    openwebui_api_key: SecretStr = Field(..., validation_alias="OPENWEBUI_API_KEY")
    openwebui_knowledge_id: str | None = Field(
        default=None, validation_alias="OPENWEBUI_KNOWLEDGE_ID"
    )
    openwebui_allowed_knowledge_ids: list[str] | None = Field(
        default=None, validation_alias="OPENWEBUI_ALLOWED_KNOWLEDGE_IDS"
    )
    openwebui_timeout_seconds: float = Field(
        default=20.0, gt=0, le=300, validation_alias="OPENWEBUI_TIMEOUT_SECONDS"
    )
    openwebui_max_retries: int = Field(
        default=2, ge=0, le=5, validation_alias="OPENWEBUI_MAX_RETRIES"
    )

    mcp_host: str = Field(default="0.0.0.0", validation_alias="MCP_HOST")
    mcp_port: int = Field(default=8000, ge=1, le=65535, validation_alias="MCP_PORT")
    mcp_auth_token: SecretStr | None = Field(default=None, validation_alias="MCP_AUTH_TOKEN")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    @field_validator("mcp_auth_token", mode="before")
    @classmethod
    def normalize_auth_token(cls, value: Any) -> Any:
        if value is None or str(value).strip() == "":
            return None
        return value

    @field_validator("openwebui_api_key", mode="after")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("OPENWEBUI_API_KEY must not be empty")
        return value

    @field_validator("openwebui_base_url", mode="after")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            raise ValueError("OPENWEBUI_BASE_URL must not be empty")
        return value

    @field_validator("openwebui_knowledge_id", mode="before")
    @classmethod
    def normalize_optional_id(cls, value: Any) -> Any:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("openwebui_allowed_knowledge_ids", mode="before")
    @classmethod
    def parse_allowlist(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            value = value.split(",")
        result = [str(item).strip() for item in value if str(item).strip()]
        return result or None

    @field_validator("log_level", mode="after")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.strip().upper()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Settings reads the required API key from the environment at runtime.
    return Settings()  # type: ignore[call-arg]
