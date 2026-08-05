from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated configuration; secrets are never rendered by Pydantic."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    environment: Literal["local", "dev", "staging", "prod"] = "local"
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str = ""
    auth_disabled: bool = False
    enable_knowledge: bool = True
    enable_account_reads: bool = True
    enable_payment_proposals: bool = False
    enable_payment_execution: bool = False
    jwt_issuer: str = ""
    jwt_audience: str = "retail-bank-a2a"
    jwt_jwks_url: str = ""

    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5.6-terra"
    openai_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"
    openai_embedding_model: str = "text-embedding-3-large"
    cohere_api_key: SecretStr = SecretStr("")
    cohere_rerank_model: str = "rerank-v3.5"
    pinecone_api_key: SecretStr = SecretStr("")
    pinecone_index: str = "retail-bank-knowledge"
    pinecone_namespace: str = "approved-policies"

    database_url: str = "postgresql+asyncpg://bank:bank@localhost:5432/bank_agents"
    redis_url: str = "redis://localhost:6379/0"
    bank_api_base_url: str = "http://localhost:8090"
    bank_api_token: SecretStr = SecretStr("")
    s3_document_bucket: str = ""
    aws_region: str = "ap-south-1"
    safety_hmac_key: SecretStr = SecretStr("local-development-key-change-me")

    max_input_chars: int = Field(default=8_000, ge=256, le=32_000)
    request_timeout_seconds: float = Field(default=25.0, ge=1, le=120)
    payment_approval_ttl_seconds: int = Field(default=600, ge=60, le=3_600)
    max_payment_amount: float = Field(default=100_000, gt=0)
    allowed_currencies: tuple[str, ...] = ("INR", "USD", "GBP", "EUR")

    @field_validator("allowed_currencies", mode="before")
    @classmethod
    def parse_currencies(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip().upper() for part in value.split(",") if part.strip())
        return value

    @field_validator("auth_disabled")
    @classmethod
    def local_auth_only(cls, value: bool, info: object) -> bool:
        # A second fail-closed check is applied at app startup after all fields are available.
        return value

    def validate_runtime(self) -> None:
        if self.environment == "prod" and self.auth_disabled:
            raise ValueError("AUTH_DISABLED cannot be true in production")
        if self.environment == "prod" and len(self.safety_hmac_key.get_secret_value()) < 32:
            raise ValueError("SAFETY_HMAC_KEY must contain at least 32 characters in production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime()
    return settings
