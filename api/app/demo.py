"""Demo personas parsed from the OpenArch users file (never exposes passwords outside this module)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

_NOOP = "{noop}"


class DemoConfigError(RuntimeError):
    """Demo mode is enabled but the users file is missing or unusable."""


@dataclass(frozen=True)
class Persona:
    username: str
    user_id: str
    label: str
    groups: tuple[str, ...]
    password: str | None  # None = encoding Studio cannot use (not {noop})


@dataclass(frozen=True)
class DemoUsers:
    personas: dict[str, Persona]
    admins: frozenset[str]
    group_ids: dict[str, str]


def load_demo_users(path: str) -> DemoUsers:
    if not path or not Path(path).is_file():
        raise DemoConfigError(f"Demo users file not found: {path!r} (set STUDIO_DEMO_USERS_FILE)")
    try:
        data = yaml.safe_load(Path(path).read_text()) or {}
    except yaml.YAMLError as exc:
        raise DemoConfigError(f"Demo users file {path!r} is not valid YAML: {exc}") from exc

    admin_groups = set(data.get("administratorsGroups") or [])
    group_ids = {g["name"]: str(g["id"]) for g in data.get("groups") or []}
    personas: dict[str, Persona] = {}
    admins: set[str] = set()
    for user in data.get("users") or []:
        groups = tuple(user.get("groups") or ())
        if admin_groups.intersection(groups):
            admins.add(user["username"])
        label = (user.get("attributes") or {}).get("studioPersona")
        if not label:
            continue
        raw = str(user.get("password") or "")
        personas[user["username"]] = Persona(
            username=user["username"],
            user_id=str(user["id"]),
            label=str(label),
            groups=groups,
            password=raw[len(_NOOP):] if raw.startswith(_NOOP) else None,
        )
    if not any(p.password is not None for p in personas.values()):
        raise DemoConfigError(f"No persona with a usable {{noop}} password in {path!r}")
    return DemoUsers(personas=personas, admins=frozenset(admins), group_ids=group_ids)
