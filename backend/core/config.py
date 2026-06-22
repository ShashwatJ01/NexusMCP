from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed process configuration validated at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NEXUS_",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    log_level: str = "INFO"
    diagnostic_log_path: str = "logs/diagnostics.jsonl"
    audit_log_path: str = "logs/audit.jsonl"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_base_url: HttpUrl | None = None
    max_agent_turns: int = Field(default=8, ge=1, le=32)
    max_history_messages: int = Field(default=40, ge=4, le=200)
    max_active_conversations: int = Field(default=2_000, ge=10, le=100_000)
    hitl_timeout_seconds: int = Field(default=300, ge=10, le=3600)

    otel_service_name: str = "nexus-mcp-backend"
    otel_exporter_otlp_endpoint: HttpUrl | None = None
    enable_console_traces: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
