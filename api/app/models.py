"""Shared request/response models for the Studio BFF."""

from __future__ import annotations

from pydantic import BaseModel, SecretStr


class Credentials(BaseModel):
    """A caller's OpenArch credentials, held only in server memory."""

    username: str
    password: SecretStr

    def basic_auth(self) -> tuple[str, str]:
        return self.username, self.password.get_secret_value()


class LoginRequest(BaseModel):
    username: str
    password: str


class SessionInfo(BaseModel):
    username: str
