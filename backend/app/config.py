"""Application configuration, loaded from environment variables.

All config is centralized here and validated at startup. No module outside
this file should read os.environ directly.
"""

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = Field(default="local")
    log_level: str = Field(default="INFO")

    # Postgres
    database_url: str = Field(
        default="postgresql+psycopg://enterprise_rag:changeme@localhost:5432/enterprise_rag"
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def rewrite_postgres_driver(cls, v: Any) -> Any:
        """Rewrite database url scheme to enforce psycopg (v3) driver connection."""
        if isinstance(v, str):
            if v.startswith("postgresql://") and not v.startswith("postgresql+psycopg://"):
                return v.replace("postgresql://", "postgresql+psycopg://", 1)
            elif v.startswith("postgres://") and not v.startswith("postgres+psycopg://"):
                return v.replace("postgres://", "postgresql+psycopg://", 1)
        return v

    # Qdrant
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str | None = Field(default=None)

    # Mistral
    mistral_api_key: str = Field(default="")
    mistral_generation_model: str = Field(default="mistral-small-latest")
    mistral_embed_model: str = Field(default="mistral-embed")

    # Auth
    jwt_secret: str = Field(default="dev-secret-change-me")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=60)

    # CORS
    allowed_origins: list[str] = Field(default=["*"])

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: Any) -> Any:
        """Parse allowed origins from a comma-separated string, JSON array, or direct list."""
        if isinstance(v, str):
            val = v.strip()
            # If it is formatted as a JSON array, decode it
            if val.startswith("[") and val.endswith("]"):
                import json
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    pass
            # Split by comma
            return [origin.strip() for origin in val.split(",") if origin.strip()]
        return v

    # Reranking
    enable_reranker: bool = Field(default=True)
    rerank_confidence_threshold: float = Field(default=0.4)
    rerank_model_name: str = Field(default="BAAI/bge-reranker-base")

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Use this everywhere instead of Settings()."""
    return Settings()
