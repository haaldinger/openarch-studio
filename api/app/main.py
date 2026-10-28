"""FastAPI application factory and router registration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from .access import router as access_router
from .auth import SessionStore
from .baseline import require_extensions
from .config import Settings, get_settings
from .demo import load_demo_users
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
from .warmup import warm_up


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.warmup_task = (
        None
        if app.state.settings.baseline_mode
        else asyncio.create_task(warm_up(app.state.settings))
    )
    try:
        yield
    finally:
        if app.state.warmup_task is not None:
            app.state.warmup_task.cancel()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="OpenArch Studio", version="0.1.0", lifespan=_lifespan)
    app.state.settings = settings
    # Runtime-mutable so the switch can flip live via PUT /api/config (no restart).
    app.state.baseline_mode = settings.baseline_mode
    app.state.sessions = SessionStore(settings.session_ttl_seconds)
    app.state.demo = load_demo_users(settings.demo_users_file) if settings.demo_mode else None
    app.state.graph = GraphService(settings)
    app.state.enrichment = EnrichmentService(
        settings, graph=app.state.graph, fields=FieldsService(settings)
    )
    app.state.reranker = Reranker(settings)
    app.include_router(router)
    app.include_router(library_router)
    app.include_router(access_router)
    app.include_router(capabilities_router)
    # Extension surfaces — disabled wholesale when baseline mode is on.
    extension_only = [Depends(require_extensions)]
    app.include_router(jobs_router, dependencies=extension_only)
    app.include_router(search_router, dependencies=extension_only)
    app.include_router(chat_router, dependencies=extension_only)
    app.include_router(graph_router, dependencies=extension_only)
    return app


app = create_app()
