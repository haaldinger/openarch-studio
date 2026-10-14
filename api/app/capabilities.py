"""Capability attribution endpoint.

Returns the native-vs-extension ledger that the UI renders. The shape is
deliberately strict so a test can prove OpenArch-native capabilities are never
attributed to Studio/Tika/Ollama, and extensions never claim native status.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api")

NATIVE_OWNER = "OpenArch"
EXTENSION_OWNERS = {"Studio", "Studio + Tika", "Studio + model"}

_NATIVE = [
    ("Document & binary storage", "SysFile documents hold the original bytes.", "/api/documents"),
    ("Folders & hierarchy", "SysFolder, sys_parentId, sys_ancestorIds subtree queries.", "/api/query"),
    ("Document deletion", "Removes a document and its children.", "DELETE /api/documents/{id}"),
    ("Document move & copy", "Reparent or duplicate within the tree.", "POST /api/documents/{id}/move"),
    ("Metadata & content models", "DocumentDTO and the model API.", "/api/model"),
    ("ACLs & effective permissions", "Per-user effective ACL.", "/api/documents/{id}/fulleffectiveacl"),
    ("Keyword & advanced HXQL queries", "Repository query engine.", "/api/query"),
    ("SysEmbeddings storage & vector search", "kNN over stored embeddings.", "/api/query/embeddings"),
    ("Users, groups & vocabularies", "Directory and vocabulary APIs.", "/api/user, /api/group"),
    ("Permission-aware retrieval", "Queries run as the caller; ACLs apply.", "Basic auth"),
    ("OpenSearch indexing", "Full-text and vector index.", "/api/query/waitForFullTextSearchIndexing"),
]

_EXTENSIONS = [
    ("Visual content workspace", "Studio", "Upload, browse, inspect documents.", "web/Library"),
    ("Scanned-image OCR", "Studio + Tika", "Tika (Tesseract) OCRs scanned images into text.", "tika:/tika"),
    ("Inline document viewer", "Studio", "Images/PDFs render in-app; TIFF converted to PNG.", "/api/documents/{id}/preview"),
    ("Text & metadata extraction", "Studio + Tika", "Tika turns binaries into text.", "tika:/tika"),
    ("Chunking & embedding", "Studio + model", "Chunks embedded then stored as SysEmbeddings.", "enrichment"),
    ("Embeddings inspection", "Studio", "Surfaces the stored vectors per chunk.", "/api/documents/{id}/embeddings"),
    ("Guided search interface", "Studio", "Keyword/HXQL/semantic in one surface.", "/api/search"),
    ("RAG orchestration & streaming chat", "Studio + model", "Grounded, cited answers over SSE.", "/api/chat"),
    ("Knowledge graph extraction & visualization", "Studio + model", "Typed entities & relations from enriched text.", "/api/graph"),
    ("Folder-scoped retrieval & graph", "Studio", "Scope search, chat & graph to one folder subtree.", "sys_ancestorIds"),
    ("Citations & retrieval trace", "Studio", "Every answer links to permitted sources.", "web/Ask"),
    ("Deletion reflected in Q&A & graph", "Studio", "Removed documents leave retrieval and the graph.", "DELETE /api/documents/{id}"),
    ("Same-origin session gateway", "Studio", "Memory-only Basic-auth session.", "/api/session"),
]

_RUNTIMES = [
    {"name": "OpenArch", "role": "System of record (documents, ACLs, vectors)"},
    {"name": "Apache Tika", "role": "Text & metadata extraction"},
    {"name": "Ollama", "role": "Local embeddings & chat (OpenAI-compatible)"},
    {"name": "Studio API", "role": "BFF, enrichment, agent orchestration"},
]


@router.get("/config")
async def config(request: Request) -> dict[str, Any]:
    """Client-readable runtime flags. Never gated, so the shell can adapt on load."""
    settings = request.app.state.settings
    return {"baselineMode": bool(getattr(settings, "baseline_mode", False))}


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, Any]:
    baseline = bool(getattr(request.app.state.settings, "baseline_mode", False))
    native = [
        {"name": n, "owner": NATIVE_OWNER, "description": d, "evidence": e} for n, d, e in _NATIVE
    ]
    extensions = [
        {"name": n, "owner": o, "description": d, "evidence": e, "disabled": baseline}
        for n, o, d, e in _EXTENSIONS
    ]
    return {
        "baselineMode": baseline,
        "native": native,
        "extensions": extensions,
        "provenanceFlow": [
            "Question",
            "Studio agent",
            "OpenArch retrieval",
            "permitted chunks",
            "configured model",
            "cited answer",
        ],
        "runtimes": _RUNTIMES,
    }
