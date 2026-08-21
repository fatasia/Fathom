from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    """Runtime configuration with strict, explicit feature switches."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FATHOM_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Environment values intentionally override YAML/init values."""

        return env_settings, dotenv_settings, init_settings, file_secret_settings

    app_name: str = "渊渟 FATHOM"
    environment: Literal["development", "test", "production"] = "development"
    storage_profile: Literal["lite", "standard"] = "lite"
    database_url: str = "sqlite:///./data/fathom.db"
    semantic_directory: Path = Path("./semantic")
    backup_directory: Path = Path("./data/backups")
    enable_duckdb: bool = True
    enable_vector_search: bool = False
    duckdb_memory_limit: str = "512MB"
    duckdb_threads: int = Field(default=2, ge=1, le=32)
    dify_console_url: str = "http://127.0.0.1"
    model_gateway: dict[str, Any] = Field(default_factory=dict)
    auth_enabled: bool = False
    auth_principals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    config_file: Path | None = None


def load_settings(config_path: Path | None = None) -> Settings:
    """Load operator YAML while preserving environment-variable precedence."""

    selected = config_path
    if selected is None:
        configured = os.getenv("FATHOM_CONFIG_FILE")
        selected = Path(configured) if configured else Path("config/fathom.yaml")
    raw: dict[str, Any] = {}
    if selected.exists():
        loaded = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Configuration root must be a mapping: {selected}")
        raw = loaded
    raw["config_file"] = selected
    return Settings(**raw)


settings = load_settings()
