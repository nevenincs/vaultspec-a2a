import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..utils.enums import Environment, LogLevel


class Settings(BaseSettings):
    """Core settings for Vaultspec A2A Orchestrator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Field(default=Environment.DEVELOPMENT)
    log_level: LogLevel = Field(default=LogLevel.INFO)
    database_url: str = Field(default="sqlite+aiosqlite:///vaultspec.db")
    workspace_root: Path = Field(
        default_factory=lambda: Path(os.environ.get("WORKSPACE_ROOT", "./workspaces"))
    )

    @property
    def is_dev(self) -> bool:
        """Check if running in development environment."""
        return self.environment == Environment.DEVELOPMENT


# Global settings instance
settings = Settings()
