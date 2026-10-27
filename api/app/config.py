"""Runtime configuration, sourced from environment variables.

All defaults target the local Compose stack so a developer can run with no
`.env` file; see `.env.example` for the overridable surface.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDIO_", env_file=".env", extra="ignore")

    # OpenArch is the system of record. Inside Compose it answers on the service name.
    openarch_url: str = "http://openarch-app:8080"
    # Apache Tika extracts text and metadata from uploaded binaries.
    tika_url: str = "http://tika:9998"
    # Text extractor: "docling" (layout-aware, Tika fallback) or "tika" only.
    extractor: str = "docling"
    docling_url: str = "http://docling:5001"
    docling_timeout_seconds: int = 300
    # Cross-encoder reranker (text-embeddings-inference). Empty = not configured.
    reranker_url: str = ""
    # Informational: the service's model is set on the reranker container.
    rerank_model: str = "BAAI/bge-reranker-base"
    # OpenAI-compatible model endpoint; Ollama is the default local runtime.
    model_base_url: str = "http://ollama:11434/v1"
    embedding_model: str = "nomic-embed-text"
    chat_model: str = "llama3.1"
    # Graph extraction is structured and high-volume; keep it on a small fast model
    # so it doesn't bottleneck behind the heavier chat model.
    graph_model: str = "llama3.2:1b"
    # Document classification + field extraction (small, structured, JSON-mode output).
    extract_model: str = "llama3.2:3b"
    # Max documents enriched at once. Extraction (Docling, Tika fallback) and embedding (Ollama) are the
    # bottlenecks; a small limit keeps a large upload batch from overloading them.
    enrich_concurrency: int = 2
    # File path for persisting the extracted knowledge graph across restarts.
    # Empty = in-memory only (used by tests); the stack sets a volume-backed path.
    graph_store_path: str = ""
    # Session lifetime for the in-memory credential store.
    session_ttl_seconds: int = 3600
    # Baseline mode: disable every Studio extension and present only native
    # OpenArch out-of-the-box capabilities. Flip with STUDIO_BASELINE_MODE=true.
    baseline_mode: bool = False
    # Emit the answer's sources as an A2UI surface the client renders from its
    # own component catalog, instead of a hardcoded citation list.
    a2ui_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
