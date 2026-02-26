from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..utils.enums import Environment, LogLevel, Model, Provider


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
    default_provider: Provider = Field(default=Provider.CLAUDE)
    default_model: Model | None = Field(default=None)
    provider_timeout_seconds: int = Field(
        default=120, description="Global timeout for LLM provider API calls."
    )
    # API Keys & Auth (with aliases for standard ecosystem names)
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"
        ),
    )
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VAULTSPEC_GEMINI_API_KEY", "GEMINI_API_KEY"),
    )
    google_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VAULTSPEC_GOOGLE_API_KEY", "GOOGLE_API_KEY"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VAULTSPEC_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    zhipu_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VAULTSPEC_ZHIPU_API_KEY", "ZHIPU_API_KEY"),
    )
    claude_code_oauth_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"
        ),
    )

    # Environment Flags
    ci: bool = Field(default=False, validation_alias=AliasChoices("VAULTSPEC_CI", "CI"))
    no_color: bool = Field(
        default=False, validation_alias=AliasChoices("VAULTSPEC_NO_COLOR", "NO_COLOR")
    )

    @property
    def is_dev(self) -> bool:
        """Check if running in development environment."""
        return self.environment == Environment.DEVELOPMENT


# Global settings instance
settings = Settings()
