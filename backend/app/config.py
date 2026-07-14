"""Application configuration, loaded from environment variables.

All config is centralized here and validated at startup. No module outside
this file should read os.environ directly.
"""

from functools import lru_cache

from pydantic import Field
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

    # Qdrant
    qdrant_url: str = Field(default="http://localhost:6333")

    # Mistral
    mistral_api_key: str = Field(default="")
    mistral_generation_model: str = Field(default="mistral-small-latest")
    mistral_embed_model: str = Field(default="mistral-embed")

    # Auth
    jwt_secret: str = Field(default="dev-secret-change-me")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_minutes: int = Field(default=60)

    # Reranking
    rerank_confidence_threshold: float = Field(default=0.4)
    rerank_model_name: str = Field(default="BAAI/bge-reranker-base")

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance. Use this everywhere instead of Settings()."""
    return Settings()
