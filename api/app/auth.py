"""In-memory session store and the auth dependency.

Credentials live only here, in the API process, keyed by an opaque session id
that the browser holds as an HTTP-only cookie. A restart drops every session.
"""

from __future__ import annotations

import secrets
import time

from fastapi import Depends, HTTPException, Request, status

from .config import Settings
from .models import Credentials
from .openarch import OpenArchClient

COOKIE_NAME = "studio_session"


class SessionStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._sessions: dict[str, tuple[Credentials, float]] = {}

    def create(self, credentials: Credentials) -> str:
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = (credentials, time.monotonic() + self._ttl)
        return session_id

    def get(self, session_id: str | None) -> Credentials | None:
        if not session_id:
            return None
        entry = self._sessions.get(session_id)
        if entry is None:
            return None
        credentials, expiry = entry
        if time.monotonic() > expiry:
            self._sessions.pop(session_id, None)
            return None
        return credentials

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


def get_openarch_client(
    credentials: Credentials = Depends(current_credentials),
    settings: Settings = Depends(get_settings_dep),
) -> OpenArchClient:
    return OpenArchClient(settings.openarch_url, credentials)
