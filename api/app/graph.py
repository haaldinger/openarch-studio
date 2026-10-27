"""Knowledge-graph extraction over enriched documents.

After a document is enriched, the local model extracts typed entities and
relations from its text (a small fixed ontology). Graphs are stored per document
in memory; the merged graph served to the UI is filtered to the documents the
caller can read, so OpenArch remains the permission authority here too.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .models import Credentials
from .openarch import OpenArchClient, OpenArchForbidden, OpenArchNotFound

# The ontology: the entity types the extractor is allowed to use.
ENTITY_TYPES = ["Person", "Organization", "Location", "Policy", "Concept", "Role", "Date"]

_PROMPT = (
    "Extract a knowledge graph from the text. Return ONLY JSON of the form "
    '{"entities":[{"name":"...","type":"..."}],'
    '"relations":[{"source":"...","target":"...","type":"..."}]}. '
    f"Each entity type MUST be one of {ENTITY_TYPES}. "
    "Use only entities that appear in the text. Relation type is a short verb phrase. "
    "Return at most 20 entities."
)


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


# Legal forms appear inconsistently across OCR'd documents, so they carry no
# identity: "Hyland Software" and "Hyland Software, Inc." are one organization.
_LEGAL_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "llc", "llp",
    "ltd", "limited", "plc", "gmbh", "mbh", "ag", "kg", "nv", "bv", "sa", "sas",
    "spa", "srl", "oy", "ab", "pty", "group", "holdings",
}


def _canonical(name: str) -> str:
    """Identity key for an entity: case, punctuation and legal-suffix insensitive."""
    words = [w for w in re.sub(r"[^\w\s&]", " ", name.lower()).split() if w]
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words) or _norm(name)


def _better_label(current: str, candidate: str) -> str:
    """Prefer a readable name: mixed case over OCR'd all-caps, then the fuller one."""
    if current.isupper() != candidate.isupper():
        return candidate if current.isupper() else current
    return candidate if len(candidate) > len(current) else current


def _is_noise(label: str) -> bool:
    """OCR'd amounts, invoice numbers, and 1-2 char fragments make poor graph nodes."""
    letters = sum(c.isalpha() for c in label)
    return letters < 3


def _resolve(name: str, entities: dict[str, dict[str, str]]) -> str | None:
    """Map a relation endpoint to an entity id, tolerating model name variants."""
    n = _canonical(name)
    if not n:
        return None
    if n in entities:
        return n
    # Lenient: the model often shortens/expands names ("Acme" vs "Acme Corporation").
    for eid in entities:
        if len(n) >= 4 and (n in eid or eid in n):
            return eid
    return None


@dataclass
class DocGraph:
    entities: dict[str, dict[str, str]] = field(default_factory=dict)  # id -> {label, type}
    relations: list[tuple[str, str, str]] = field(default_factory=list)  # (source_id, target_id, type)


class GraphStore:
    def __init__(self, path: str = "") -> None:
        self._path = path
        self._graphs: dict[str, DocGraph] = {}
        if path and os.path.exists(path):
            self._load()

    def _load(self) -> None:
        try:
            with open(self._path) as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return
        for doc_id, g in data.items():
            self._graphs[doc_id] = DocGraph(
                entities=g.get("entities", {}),
                relations=[tuple(r) for r in g.get("relations", [])],
            )

    def _save(self) -> None:
        if not self._path:
            return
        data = {
            doc_id: {"entities": g.entities, "relations": [list(r) for r in g.relations]}
            for doc_id, g in self._graphs.items()
        }
        tmp = f"{self._path}.tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, self._path)

    def put(self, doc_id: str, graph: DocGraph) -> None:
        self._graphs[doc_id] = graph
        self._save()

    def remove(self, doc_id: str) -> None:
        if self._graphs.pop(doc_id, None) is not None:
            self._save()

    def get(self, doc_id: str) -> DocGraph | None:
        return self._graphs.get(doc_id)

    def doc_ids(self) -> list[str]:
        return list(self._graphs)


def parse_graph(raw: str) -> DocGraph:
    """Parse the model's JSON graph defensively (tolerates code fences / prose)."""
    text = raw.strip()
    if "```" in text:
        text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return DocGraph()
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return DocGraph()

    graph = DocGraph()
    for ent in data.get("entities", []):
        name = str(ent.get("name", "")).strip()
        etype = str(ent.get("type", "")).strip()
        if not name or etype not in ENTITY_TYPES:
            continue
        graph.entities[_canonical(name)] = {"label": name, "type": etype}
    for rel in data.get("relations", []):
        source = _resolve(str(rel.get("source", "")), graph.entities)
        target = _resolve(str(rel.get("target", "")), graph.entities)
        rtype = str(rel.get("type", "")).strip() or "related to"
        if source and target and source != target:
            graph.relations.append((source, target, rtype))
    return graph


class GraphService:
    def __init__(self, settings: Settings, store: GraphStore | None = None) -> None:
        self._settings = settings
        self.store = store or GraphStore(settings.graph_store_path)

    async def _complete(self, text: str) -> str:
        url = f"{self._settings.model_base_url}/chat/completions"
        payload = {
            "model": self._settings.extract_model,
            "messages": [
                {"role": "system", "content": _PROMPT},
                {"role": "user", "content": text[:3500]},
            ],
            "stream": False,
        }
        # CPU inference of structured output is slow; allow generous time.
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    async def extract(self, doc_id: str, text: str) -> DocGraph:
        graph = parse_graph(await self._complete(text))
        self.store.put(doc_id, graph)
        return graph

    async def merged(self, credentials: Credentials, scope: str | None = None) -> dict[str, Any]:
        """Union of stored graphs, limited to documents the caller may read.

        A scope (folder id) further restricts to that folder's subtree via
        sys_ancestorIds. Noise entities are dropped, and each document's entities
        are linked to its vendor (an inferred co-occurrence edge) so the graph
        clusters per invoice instead of floating as disconnected points.
        """
        client = OpenArchClient(self._settings.openarch_url, credentials)
        nodes: dict[str, dict[str, Any]] = {}
        model_edges: list[dict[str, Any]] = []
        doc_node_ids: dict[str, list[str]] = {}

        for doc_id in self.store.doc_ids():
            try:
                doc = await client.get_document(doc_id)
            except (OpenArchForbidden, OpenArchNotFound):
                continue
            if scope and scope not in (doc.get("sys_ancestorIds") or []):
                continue
            graph = self.store.get(doc_id)
            if graph is None:
                continue
            surviving: list[str] = []
            # Re-canonicalize on read so graphs stored before this ran still merge.
            alias: dict[str, str] = {}
            for node_id, meta in graph.entities.items():
                if _is_noise(meta["label"]):
                    continue
                merged_id = f"{meta['type']}:{_canonical(meta['label'])}"
                alias[node_id] = merged_id
                node = nodes.get(merged_id)
                if node is None:
                    node = nodes[merged_id] = {
                        "id": merged_id,
                        "label": meta["label"],
                        "type": meta["type"],
                        "docIds": [],
                    }
                else:
                    node["label"] = _better_label(node["label"], meta["label"])
                if doc_id not in node["docIds"]:
                    node["docIds"].append(doc_id)
                if merged_id not in surviving:
                    surviving.append(merged_id)
            doc_node_ids[doc_id] = surviving
            for source, target, rtype in graph.relations:
                start, end = alias.get(source), alias.get(target)
                if start and end and start != end:
                    model_edges.append(
                        {"source": start, "target": end, "type": rtype, "inferred": False}
                    )

        edges = list(model_edges)
        for ids in doc_node_ids.values():
            if len(ids) < 2:
                continue
            hub = next((i for i in ids if nodes[i]["type"] == "Organization"), ids[0])
            for node_id in ids:
                if node_id != hub:
                    edges.append({"source": hub, "target": node_id, "type": "appears with", "inferred": True})

        # Merging nodes collapses distinct endpoints onto the same pair.
        unique: dict[tuple[str, str, str], dict[str, Any]] = {}
        for edge in edges:
            unique.setdefault((edge["source"], edge["target"], edge["type"]), edge)

        return {"nodes": list(nodes.values()), "edges": list(unique.values()), "entityTypes": ENTITY_TYPES}
