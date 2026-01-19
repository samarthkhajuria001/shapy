"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "Shapy"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"

    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "sqlite+aiosqlite:///./shapy.db"

    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-5-nano"
    openai_embedding_model: str = "text-embedding-3-small"

    cors_origins: list[str] = ["http://localhost:4200", "http://localhost:3000"]

    # Indexing settings
    chroma_path: str = "./data/chroma"
    chroma_collection: str = "documents"
    enrichment_model: str = "gpt-4o"
    enrichment_batch_size: int = 10
    enrichment_max_concurrent: int = 5
    vision_model: str = "gpt-4o"

    # Chunking settings
    chunk_target_size: int = 600
    chunk_min_size: int = 200
    chunk_max_size: int = 1000
    chunk_overlap: int = 100
    parent_soft_limit_tokens: int = 600

    # Retrieval settings
    retrieval_top_k_per_query: int = 8
    retrieval_top_n_parents: int = 3
    retrieval_rrf_k: int = 60
    enable_query_expansion: bool = True
    enable_bm25: bool = True
    enable_xref_expansion: bool = True

    session_ttl_hours: int = 24
    max_sessions_per_user: int = 3
    max_objects_per_context: int = 100
    max_points_per_polyline: int = 500
    max_layers_per_context: int = 25
    max_context_size_kb: int = 2048
    context_size_warning_kb: int = 500

    # Agent settings
    agent_model: str = "gpt-4o"
    agent_temperature: float = 0.1
    agent_max_tokens: int = 2000
    agent_classifier_model: str = "gpt-4o-mini"
    agent_clarifier_model: str = "gpt-4o-mini"
    agent_max_clarification_rounds: int = 3
    agent_context_token_budget: int = 4000
    agent_enable_assumptions: bool = True
    agent_enable_clarifications: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
