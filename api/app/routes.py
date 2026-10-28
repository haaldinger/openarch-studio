"""HTTP routes for the Studio BFF."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .auth import (
    COOKIE_NAME,
    Session,
    SessionStore,
    current_session,
    get_session_store,
    get_settings_dep,
    is_demo_admin,
    persona_credentials,
    require_demo_admin,
)
from .config import Settings
from .demo import DemoUsers
from .models import ActAsRequest, Credentials, LoginRequest, PersonaInfo, SessionInfo

router = APIRouter(prefix="/api")


def _session_info(session: Session, demo: DemoUsers | None) -> SessionInfo:
    acting_as = None
    if demo is not None and session.active.username != session.origin.username:
        persona = demo.personas.get(session.active.username)
        if persona is not None:
            acting_as = PersonaInfo(
                username=persona.username, label=persona.label, groups=list(persona.groups)
            )
    return SessionInfo(
        username=session.origin.username,
        actingAs=acting_as,
        demoAdmin=is_demo_admin(demo, session),
    )


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
    request: Request,
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
    return _session_info(Session(origin=credentials, active=credentials), request.app.state.demo)


@router.get("/session", response_model=SessionInfo)
async def read_session(request: Request, session: Session = Depends(current_session)) -> SessionInfo:
    return _session_info(session, request.app.state.demo)


@router.post("/session/act-as", response_model=SessionInfo)
async def act_as(
    body: ActAsRequest,
    request: Request,
    session: Session = Depends(current_session),
    demo: DemoUsers = Depends(require_demo_admin),
    store: SessionStore = Depends(get_session_store),
    settings: Settings = Depends(get_settings_dep),
) -> SessionInfo:
    from .openarch import OpenArchClient, OpenArchError, OpenArchUnavailable

    target = persona_credentials(demo, body.username, session.origin)
    if target is not session.origin:
        try:
            await OpenArchClient(settings.openarch_url, target).authenticate()
        except OpenArchUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OpenArch is unreachable"
            ) from None
        except OpenArchError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Couldn't sign in as {body.username}; check the demo users file",
            ) from None
    store.set_active(request.cookies.get(COOKIE_NAME), target)
    return _session_info(session, demo)


@router.get("/demo/personas")
async def list_personas(
    request: Request, _session: Session = Depends(current_session)
) -> list[dict[str, object]]:
    demo: DemoUsers | None = request.app.state.demo
    if demo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return [
        {
            "username": p.username,
            "label": p.label,
            "groups": list(p.groups),
            "available": p.password is not None,
        }
        for p in demo.personas.values()
    ]


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    request: Request,
    response: Response,
    store: SessionStore = Depends(get_session_store),
) -> None:
    store.delete(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
