from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Financial Report RAG Analyzer"
    api_prefix: str = ""
    storage_dir: str = "storage/reports"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    openai_api_key: str | None = None
    llm_provider: str = "openai"
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"

    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "llama3.1"
    local_embedding_model: str = "nomic-embed-text"

    vector_store: str = "faiss"
    chunk_size: int = 1200
    chunk_overlap: int = 150

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def storage_path(self) -> Path:
        raw = Path(self.storage_dir)
        if raw.is_absolute():
            return raw
        backend_root = Path(__file__).resolve().parents[2]
        return (backend_root / raw).resolve()


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    return settings
