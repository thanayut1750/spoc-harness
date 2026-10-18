"""Validated application settings; never load credentials into model prompts."""

import os
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from org_harness.models import ModelSelection, RunLimits


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
    model_timeout: float = Field(default=300, gt=0)
    # Z.AI's output allowance includes thinking. 8K can expire before the first
    # visible answer when max reasoning is enabled on document-heavy tasks.
    model_max_tokens: int = Field(default=32768, ge=256)
    typesafe_api_key: SecretStr = SecretStr("")
    typesafe_model: str = "jev-1.13.0"
    typesafe_base_url: str = "https://api.typesafe.ai"
    typesafe_timeout: float = Field(default=8, gt=0, le=30)
    zai_api_key: SecretStr = SecretStr("")
    zai_base_url: str = "https://api.z.ai/api/coding/paas/v4"
    zai_model: str = "glm-5.3-flash"
    standard_openai_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="SPOC_OPENAI_API_KEY"
    )
    standard_openai_model: str = Field(default="gpt-5", validation_alias="SPOC_OPENAI_MODEL")
    compatible_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="SPOC_COMPATIBLE_API_KEY"
    )
    compatible_base_url: str = Field(default="", validation_alias="SPOC_COMPATIBLE_BASE_URL")
    compatible_model: str = Field(default="", validation_alias="SPOC_COMPATIBLE_MODEL")
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
            "triage_configured": bool(self.typesafe_api_key.get_secret_value()),
        }

    def default_model_selection(self) -> ModelSelection:
        return ModelSelection.model_validate(
            {
                "provider": "configured",
                "model": self.main_model,
                "reasoning_effort": self.reasoning_effort,
            }
        )

    def provider_connection(self, provider: str) -> tuple[str, SecretStr, bool]:
        """Resolve credentials only on the server; never store them in a run."""
        if provider == "configured":
            from urllib.parse import urlsplit

            host = urlsplit(self.openai_base_url).hostname or ""
            return (
                self.openai_base_url,
                self.openai_api_key,
                host == "z.ai" or host.endswith(".z.ai"),
            )
        if provider == "zai":
            key = self.zai_api_key
            if not key.get_secret_value() and self.provider_connection("configured")[2]:
                key = self.openai_api_key
            return self.zai_base_url, key, True
        if provider == "openai":
            return "https://api.openai.com/v1", self.standard_openai_api_key, False
        if provider == "openai_compatible":
            return self.compatible_base_url, self.compatible_api_key, False
        raise ValueError("Unknown provider")

    def validate_model_selection(self, value: ModelSelection) -> ModelSelection:
        base, key, _ = self.provider_connection(value.provider)
        if not base or (not key.get_secret_value() and not self.harness_test_mode):
            raise ValueError("Provider is not configured on the server")
        if value.reasoning_effort not in self.provider_reasoning_efforts(value.provider):
            raise ValueError("Reasoning effort is not supported by this provider")
        return value

    def provider_reasoning_efforts(self, provider: str) -> list[str]:
        from urllib.parse import urlsplit

        base, _, zai = self.provider_connection(provider)
        if not zai and urlsplit(base).hostname == "api.openai.com":
            return ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
        return ["none", "minimal", "low", "medium", "high", "max"]

    def public_settings(
        self, selection: dict | None = None, agent_models: dict | None = None
    ) -> dict:
        defaults = self.default_model_selection().model_dump()
        names = {
            "configured": ("Configured endpoint", self.main_model),
            "zai": ("Z.AI", self.zai_model),
            "openai": ("OpenAI (Chat Completions)", self.standard_openai_model),
            "openai_compatible": ("OpenAI compatible", self.compatible_model),
        }
        providers = []
        for provider, (label, model) in names.items():
            base, key, _ = self.provider_connection(provider)
            providers.append(
                {
                    "id": provider,
                    "label": label,
                    "configured": bool(base and (key.get_secret_value() or self.harness_test_mode)),
                    "default_model": model,
                    "reasoning_efforts": self.provider_reasoning_efforts(provider),
                }
            )
        return {
            "defaults": defaults,
            "model_config": selection or defaults,
            "agent_model_configs": agent_models or {},
            "providers": providers,
            "triage": {
                "model": self.typesafe_model,
                "configured": bool(self.typesafe_api_key.get_secret_value()),
            },
            "worker_timeout": RunLimits().worker_timeout,
        }


def configure_tracing(settings: Settings) -> None:
    """Export explicit opt-in tracing settings for LangChain's SDK callbacks."""
    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"
    if settings.langsmith_tracing:
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        if settings.langsmith_api_key.get_secret_value():
            os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
