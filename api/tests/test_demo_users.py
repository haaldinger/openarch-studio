"""Demo users file loading and demo-mode settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.demo import DemoConfigError, load_demo_users
from app.main import create_app

REAL_FILE = str(Path(__file__).resolve().parents[2] / "demo" / "openarch-users.yml")


def _write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "users.yml"
    path.write_text(text)
    return str(path)


def test_loads_personas_and_admins() -> None:
    demo = load_demo_users(REAL_FILE)
    assert set(demo.personas) == {"fiona", "henry", "sam", "erin", "cory"}
    assert demo.personas["erin"].groups == ("finance", "hr", "sales", "members")
    assert demo.personas["sam"].label == "Sales rep"
    assert demo.personas["sam"].password == "password"
    assert "password" not in repr(demo.personas["sam"])
    assert "admin" in demo.admins
    assert demo.group_ids["sales"] == "3f1a0c52-6b0e-4d7e-9a51-0c3d7e2a1f03"


def test_bcrypt_persona_is_unavailable(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
administratorsGroups: [administrators]
groups:
  - {id: g1, name: members}
users:
  - {id: u1, username: ok, password: "{noop}pw", groups: [members], attributes: {studioPersona: Ok}}
  - {id: u2, username: locked, password: "{bcrypt}$2a$10$abc", groups: [members], attributes: {studioPersona: Locked}}
""",
    )
    demo = load_demo_users(path)
    assert demo.personas["locked"].password is None
    assert demo.personas["ok"].password == "pw"


def test_no_usable_persona_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
users:
  - {id: u2, username: locked, password: "{bcrypt}$2a$10$abc", groups: [members], attributes: {studioPersona: Locked}}
""",
    )
    with pytest.raises(DemoConfigError):
        load_demo_users(path)


@pytest.mark.parametrize("path", ["", "/nonexistent/users.yml"])
def test_missing_path_raises_demo_config_error(path: str) -> None:
    with pytest.raises(DemoConfigError):
        load_demo_users(path)


def test_config_reports_demo_mode(settings: Settings) -> None:
    demo_settings = settings.model_copy(update={"demo_mode": True, "demo_users_file": REAL_FILE})
    assert TestClient(create_app(demo_settings)).get("/api/config").json()["demoMode"] is True
    assert TestClient(create_app(settings)).get("/api/config").json()["demoMode"] is False


def test_demo_mode_without_file_fails_startup(settings: Settings) -> None:
    broken = settings.model_copy(update={"demo_mode": True, "demo_users_file": ""})
    with pytest.raises(DemoConfigError):
        create_app(broken)
