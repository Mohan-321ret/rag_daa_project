from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyUrl
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = "FinalYear Project API"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change_me"

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+psycopg2://postgres:postgres@localhost:5432/finalyear_db"
    )

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_password"

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_provider: str = "ollama"  # ollama | openai | groq

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    groq_api_key: str = ""
    groq_model: str = "llama3-8b-8192"

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # ── FAISS ─────────────────────────────────────────────────────────────────
    faiss_index_path: str = "./data/faiss_index"

    # ── Document Ingestion ────────────────────────────────────────────────────
    max_upload_size_mb: int = 25
    temp_upload_dir: str = "./data/tmp_uploads"
    doc_id_prefix: str = "DOC"
    # Comma-separated list of allowed MIME types / extensions
    allowed_extensions: str = ".pdf,.docx,.txt,.html,.pptx"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def allowed_ext_list(self) -> list[str]:
        return [e.strip().lower() for e in self.allowed_extensions.split(",")]

    # ── CORS ──────────────────────────────────────────────────────────────────
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


settings = Settings()
