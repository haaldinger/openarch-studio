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
    # OpenAI-compatible model endpoint; Ollama is the default local runtime.
    model_base_url: str = "http://ollama:11434/v1"
    embedding_model: str = "nomic-embed-text"
    chat_model: str = "llama3.1"
    # Graph extraction is structured and high-volume; keep it on a small fast model
    # so it doesn't bottleneck behind the heavier chat model.
    graph_model: str = "llama3.2:1b"
    # Max documents enriched at once. OCR (Tika) and embedding (Ollama) are the
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
