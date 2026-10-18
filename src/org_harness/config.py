"""Validated application settings; never load credentials into model prompts."""

import os
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    openai_base_url: str = "https://api.z.ai/api/coding/paas/v4"
    openai_api_key: SecretStr = SecretStr("")
    main_model: str = "glm-5.3-flash"
    reasoning_effort: str = Field(
        default="max", validation_alias=AliasChoices("REASONING_EFFORT", "REASIONING_EFFORT")
    )
    database_url: SecretStr = SecretStr("postgresql://spoc:spoc@127.0.0.1:5432/spoc")
    data_dir: Path = Field(default=Path(".harness"), validation_alias="SPOC_DATA_DIR")
    api_host: str = Field(default="127.0.0.1", validation_alias="SPOC_API_HOST")
    api_port: int = Field(default=8000, ge=1, le=65535, validation_alias="SPOC_API_PORT")
    harness_test_mode: bool = False
    storage_backend: Literal["postgres", "memory"] = "postgres"
    model_timeout: float = Field(default=180, gt=0)
    model_max_tokens: int = Field(default=8192, ge=256)
    search_mcp_url: str = "https://api.z.ai/api/mcp/web_search_prime/mcp"
    reader_mcp_url: str = "https://api.z.ai/api/mcp/web_reader/mcp"
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr = SecretStr("")
    langsmith_project: str = "spoc-harness"

    def redacted(self) -> dict[str, object]:
        return {
            "model": self.main_model,
            "reasoning_effort": self.reasoning_effort,
            "api_key_configured": bool(self.openai_api_key.get_secret_value()),
            "database_configured": bool(self.database_url.get_secret_value()),
            "data_dir": str(self.data_dir.resolve()),
            "test_mode": self.harness_test_mode,
            "storage_backend": self.storage_backend,
        }


def configure_tracing(settings: Settings) -> None:
    """Export explicit opt-in tracing settings for LangChain's SDK callbacks."""
    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"
    if settings.langsmith_tracing:
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        if settings.langsmith_api_key.get_secret_value():
            os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
