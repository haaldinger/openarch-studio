"""In-memory session store and the auth dependency.

Credentials live only here, in the API process, keyed by an opaque session id
that the browser holds as an HTTP-only cookie. A restart drops every session.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from .config import Settings
from .demo import DemoUsers
from .models import Credentials
from .openarch import OpenArchClient

COOKIE_NAME = "studio_session"


@dataclass
class Session:
    origin: Credentials  # who signed in
    active: Credentials  # who requests run as (differs while acting as a persona)


class SessionStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, tuple[Session, float]] = {}

    def create(self, credentials: Credentials) -> str:
        session_id = secrets.token_urlsafe(32)
        session = Session(origin=credentials, active=credentials)
        self._sessions[session_id] = (session, time.monotonic() + self._ttl)
        return session_id

    def get_session(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        entry = self._sessions.get(session_id)
        if entry is None:
            return None
        session, expiry = entry
        if time.monotonic() > expiry:
            self._sessions.pop(session_id, None)
            return None
        return session

    def get(self, session_id: str | None) -> Credentials | None:
        session = self.get_session(session_id)
        return session.active if session else None

    def set_active(self, session_id: str | None, credentials: Credentials) -> None:
        session = self.get_session(session_id)
        if session is not None:
            session.active = credentials

    def delete(self, session_id: str | None) -> None:
        if session_id:
            self._sessions.pop(session_id, None)


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.sessions


def current_credentials(
    request: Request,
    store: SessionStore = Depends(get_session_store),
) -> Credentials:
    credentials = store.get(request.cookies.get(COOKIE_NAME))
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return credentials


def current_session(
    request: Request,
    store: SessionStore = Depends(get_session_store),
) -> Session:
    session = store.get_session(request.cookies.get(COOKIE_NAME))
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return session


def origin_credentials(session: Session = Depends(current_session)) -> Credentials:
    return session.origin


def is_demo_admin(demo: DemoUsers | None, session: Session) -> bool:
    return demo is not None and session.origin.username in demo.admins


def require_demo_admin(
    request: Request,
    session: Session = Depends(current_session),
) -> DemoUsers:
    demo: DemoUsers | None = getattr(request.app.state, "demo", None)
    if demo is None or not is_demo_admin(demo, session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
    return demo


def persona_credentials(demo: DemoUsers, username: str, origin: Credentials) -> Credentials:
    if username == origin.username:
        return origin
    persona = demo.personas.get(username)
    if persona is None or persona.password is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
    return Credentials(username=persona.username, password=persona.password)


def get_openarch_client(
    credentials: Credentials = Depends(current_credentials),
    settings: Settings = Depends(get_settings_dep),
) -> OpenArchClient:
    return OpenArchClient(settings.openarch_url, credentials)
