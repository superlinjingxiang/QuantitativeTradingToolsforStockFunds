"""Typed settings for local runtime configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application settings loaded from environment variables when present."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CQP_",
        extra="ignore",
    )

    app_name: str = "china_quant_platform"
    environment: str = "development"
    log_level: str = "INFO"
    data_dir: Path = Path("data")
    logs_dir: Path = Path("logs")
    reports_dir: Path = Path("reports")
