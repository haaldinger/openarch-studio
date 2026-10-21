"""The A2UI surface builder must stay inside the catalog the renderer knows."""

from __future__ import annotations

import pytest

from app import a2ui


def _messages():
    return a2ui.sources_surface("s1", [{"docId": "d1", "title": "Policy"}, {"docId": "d2"}])


def test_message_order_creates_surface_last() -> None:
    keys = [next(k for k in m if k != "version") for m in _messages()]
    assert keys == ["updateComponents", "updateDataModel", "createSurface"]


def test_every_component_type_is_in_the_catalog() -> None:
    components = _messages()[0]["updateComponents"]["components"]
    for entry in components:
        [kind] = entry["component"].keys()
        assert kind in a2ui.SUPPORTED_COMPONENTS


def test_children_reference_declared_components() -> None:
    components = _messages()[0]["updateComponents"]["components"]
    ids = {c["id"] for c in components}
    for entry in components:
        [props] = entry["component"].values()
        referenced = props.get("children", {}).get("explicitList", [])
        if isinstance(props.get("child"), str):
            referenced = [*referenced, props["child"]]
        assert set(referenced) <= ids


def test_buttons_dispatch_agent_events_not_urls() -> None:
    """A document must never be able to steer the client to an arbitrary URL."""
    components = _messages()[0]["updateComponents"]["components"]
    actions = [
        props["action"]
        for entry in components
        for props in entry["component"].values()
        if "action" in props
    ]
    assert actions
    for action in actions:
        assert "event" in action
        assert "functionCall" not in action


def test_unknown_component_is_rejected() -> None:
    with pytest.raises(ValueError):
        a2ui._component("x", "ScriptTag", {})


def test_titles_fall_back_to_doc_id() -> None:
    contents = _messages()[1]["updateDataModel"]["contents"]
    second = contents[0]["valueMap"][1]["valueMap"]
    assert {"key": "title", "valueString": "d2"} in second
