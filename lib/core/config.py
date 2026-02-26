from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..utils.enums import Environment, LogLevel


class Settings(BaseSettings):
    """Core settings for Vaultspec A2A Orchestrator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VAULTSPEC_",
        extra="ignore",
    )

    environment: Environment = Field(default=Environment.DEVELOPMENT)
    log_level: LogLevel = Field(default=LogLevel.INFO)
    database_url: str = Field(default="sqlite+aiosqlite:///vaultspec.db")
    workspace_root: Path = Field(default=Path("./workspaces"))
    provider_timeout_seconds: int = Field(
        default=120, description="Global timeout for LLM provider API calls."
    )

    @property
    def is_dev(self) -> bool:
        """Check if running in development environment."""
        return self.environment == Environment.DEVELOPMENT


# Global settings instance
settings = Settings()
