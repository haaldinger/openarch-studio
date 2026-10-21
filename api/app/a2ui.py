"""A2UI v0.9 surface composition.

Studio composes surfaces server-side from evidence it has already
permission-checked. The model decides *whether* a surface is worth showing; it
never emits component JSON. That matters here because retrieved context is
untrusted — a malicious document must not be able to inject UI.

Messages follow the v0.9 ordering: components and data first, `createSurface`
last. Components are a flat adjacency list referencing children by id.
"""

from __future__ import annotations

from typing import Any

VERSION = "v0.9"
CATALOG_ID = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"

# Must stay a subset of the renderer catalog in web/src/components/a2ui/catalog.tsx.
SUPPORTED_COMPONENTS = frozenset({"Card", "Column", "Row", "Text", "Divider", "Button"})

MAX_SOURCES = 4


def _component(cid: str, kind: str, props: dict[str, Any]) -> dict[str, Any]:
    if kind not in SUPPORTED_COMPONENTS:
        raise ValueError(f"{kind} is not in the Studio A2UI catalog")
    return {"id": cid, "component": {kind: props}}


def _entry(key: str, value: str) -> dict[str, str]:
    return {"key": key, "valueString": value}


def sources_surface(surface_id: str, citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the 'Sources' surface for one answer as a list of A2UI messages."""
    shown = citations[:MAX_SOURCES]
    row_ids = [f"row-{i}" for i in range(len(shown))]

    components: list[dict[str, Any]] = [
        _component("root", "Card", {"child": "body"}),
        _component(
            "body",
            "Column",
            {"children": {"explicitList": ["title", "rule", *row_ids, "footer"]}},
        ),
        _component("title", "Text", {"text": {"literalString": "Sources"}, "usageHint": "h5"}),
        _component("rule", "Divider", {"axis": "horizontal"}),
        _component(
            "footer",
            "Text",
            {
                "text": {"literalString": "Composed by the agent as an A2UI surface."},
                "usageHint": "caption",
            },
        ),
    ]

    for i in range(len(shown)):
        components += [
            _component(
                row_ids[i],
                "Row",
                {
                    "children": {"explicitList": [f"label-{i}", f"open-{i}"]},
                    "justify": "spaceBetween",
                    "align": "center",
                },
            ),
            _component(f"label-{i}", "Text", {"text": {"path": f"/sources/{i}/title"}}),
            _component(
                f"open-{i}",
                "Button",
                {
                    "child": f"open-text-{i}",
                    "variant": "borderless",
                    # An agent event, not a functionCall: the host decides what
                    # "open" means, so the payload can never carry a URL.
                    "action": {
                        "event": {
                            "name": "open_document",
                            "context": {"docId": {"path": f"/sources/{i}/docId"}},
                        }
                    },
                },
            ),
            _component(f"open-text-{i}", "Text", {"text": {"literalString": "Open"}}),
        ]

    contents = [
        {
            "key": "sources",
            "valueMap": [
                {
                    "key": str(i),
                    "valueMap": [
                        _entry("title", str(c.get("title") or c.get("docId") or "Untitled")),
                        _entry("docId", str(c.get("docId") or "")),
                        _entry("chunkId", str(c.get("chunkId") or "")),
                    ],
                }
                for i, c in enumerate(shown)
            ],
        }
    ]

    return [
        {
            "version": VERSION,
            "updateComponents": {"surfaceId": surface_id, "components": components},
        },
        {
            "version": VERSION,
            "updateDataModel": {"surfaceId": surface_id, "contents": contents},
        },
        {
            "version": VERSION,
            "createSurface": {
                "surfaceId": surface_id,
                "root": "root",
                "catalogId": CATALOG_ID,
            },
        },
    ]
