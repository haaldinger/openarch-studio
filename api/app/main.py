"""FastAPI application factory and router registration."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from .auth import SessionStore
from .baseline import require_extensions
from .config import Settings, get_settings
from .enrichment import EnrichmentService
from .fields import FieldsService
from .graph import GraphService
from .jobs import router as jobs_router
from .library import router as library_router
from .rerank import Reranker
from .routes import router
from .search import router as search_router
from .chat import router as chat_router
from .capabilities import router as capabilities_router
from .graphapi import router as graph_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="OpenArch Studio", version="0.1.0")
    app.state.settings = settings
    # Runtime-mutable so the switch can flip live via PUT /api/config (no restart).
    app.state.baseline_mode = settings.baseline_mode
    app.state.sessions = SessionStore(settings.session_ttl_seconds)
    app.state.graph = GraphService(settings)
    app.state.enrichment = EnrichmentService(
        settings, graph=app.state.graph, fields=FieldsService(settings)
    )
    app.state.reranker = Reranker(settings)
    app.include_router(router)
    app.include_router(library_router)
    app.include_router(capabilities_router)
    # Extension surfaces — disabled wholesale when baseline mode is on.
    extension_only = [Depends(require_extensions)]
    app.include_router(jobs_router, dependencies=extension_only)
    app.include_router(search_router, dependencies=extension_only)
    app.include_router(chat_router, dependencies=extension_only)
    app.include_router(graph_router, dependencies=extension_only)
    return app


app = create_app()
