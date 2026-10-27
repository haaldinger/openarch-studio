"""Model-role settings: extract model aliasing and chat default."""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("STUDIO_EXTRACT_MODEL", "STUDIO_GRAPH_MODEL", "STUDIO_CHAT_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_graph_model_env_is_alias_for_extract_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_GRAPH_MODEL", "tiny")
    assert Settings(_env_file=None).extract_model == "tiny"


def test_extract_model_env_wins_over_graph_model_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STUDIO_GRAPH_MODEL", "tiny")
    monkeypatch.setenv("STUDIO_EXTRACT_MODEL", "big")
    assert Settings(_env_file=None).extract_model == "big"


def test_extract_model_keyword_construction_still_works() -> None:
    assert Settings(_env_file=None, extract_model="kw").extract_model == "kw"


def test_chat_default_is_light() -> None:
    assert Settings(_env_file=None).chat_model == "llama3.2:3b"
