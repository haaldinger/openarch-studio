"""HTTP routes for the Studio BFF."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .auth import (
    COOKIE_NAME,
    SessionStore,
    current_credentials,
    get_session_store,
    get_settings_dep,
)
from .config import Settings
from .models import Credentials, LoginRequest, SessionInfo

router = APIRouter(prefix="/api")


async def _probe(client: httpx.AsyncClient, url: str) -> str:
    try:
        response = await client.get(url, timeout=2.0)
        return "up" if response.status_code < 500 else "degraded"
    except httpx.HTTPError:
        return "down"


@router.get("/health")
async def health(settings: Settings = Depends(get_settings_dep)) -> dict[str, str]:
    async with httpx.AsyncClient() as client:
        openarch = await _probe(client, f"{settings.openarch_url}/actuator/health")
        tika = await _probe(client, f"{settings.tika_url}/version")
        model = await _probe(client, f"{settings.model_base_url}/models")
    return {"status": "ok", "openarch": openarch, "tika": tika, "model": model}


@router.post("/session", response_model=SessionInfo)
async def create_session(
    body: LoginRequest,
    response: Response,
    store: SessionStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings_dep),
) -> SessionInfo:
    from .openarch import (
        OpenArchAuthError,
        OpenArchClient,
        OpenArchUnavailable,
    )

    credentials = Credentials(username=body.username, password=body.password)
    client = OpenArchClient(settings.openarch_url, credentials)
    try:
        await client.authenticate()
    except OpenArchAuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password"
        ) from None
    except OpenArchUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OpenArch is unreachable"
        ) from None

    session_id = store.create(credentials)
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return SessionInfo(username=credentials.username)


@router.get("/session", response_model=SessionInfo)
async def read_session(credentials: Credentials = Depends(current_credentials)) -> SessionInfo:
    return SessionInfo(username=credentials.username)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    request: Request,
    response: Response,
    store: SessionStore = Depends(get_session_store),
) -> None:
    store.delete(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
