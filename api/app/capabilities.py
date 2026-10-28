"""Capability attribution endpoint.

Returns the native-vs-extension ledger that the UI renders. The shape is
deliberately strict so a test can prove OpenArch-native capabilities are never
attributed to Studio/Tika/Ollama, and extensions never claim native status.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .auth import current_credentials
from .models import Credentials

router = APIRouter(prefix="/api")

NATIVE_OWNER = "OpenArch"
EXTENSION_OWNERS = {"Studio", "Studio + Docling (Tika fallback)", "Studio + model"}

_NATIVE = [
    ("Document & binary storage", "SysFile documents hold the original bytes.", "/api/documents"),
    ("Folders & hierarchy", "SysFolder, sys_parentId, sys_ancestorIds subtree queries.", "/api/query"),
    ("Document deletion", "Removes a document and its children.", "DELETE /api/documents/{id}"),
    ("Document move & copy", "Reparent or duplicate within the tree.", "POST /api/documents/{id}/move"),
    ("Metadata & content models", "DocumentDTO, the model API and the CinContext mixin that holds extracted fields.", "/api/model, CinContext"),
    ("ACLs & effective permissions", "Per-user effective ACL.", "/api/documents/{id}/fulleffectiveacl"),
    ("Keyword & advanced HXQL queries", "Repository query engine.", "/api/query"),
    ("SysEmbeddings storage & vector search", "kNN over stored embeddings.", "/api/query/embeddings"),
    ("Users, groups & vocabularies", "Directory and vocabulary APIs.", "/api/user, /api/group"),
    ("Permission-aware retrieval", "Queries run as the caller; ACLs apply.", "Basic auth"),
    ("OpenSearch indexing", "Full-text and vector index.", "/api/query/waitForFullTextSearchIndexing"),
]

_EXTENSIONS = [
    ("Visual content workspace", "Studio", "Upload, browse, inspect documents.", "web/Library"),
    ("Scanned-image OCR", "Studio + Docling (Tika fallback)", "Docling OCRs scanned images and PDFs into Markdown; Tika (Tesseract) is the fallback.", "extraction.py"),
    ("Inline document viewer", "Studio", "Images/PDFs render in-app; TIFF converted to PNG.", "/api/documents/{id}/preview"),
    ("Text & metadata extraction", "Studio + Docling (Tika fallback)", "Docling turns binaries into page-aware Markdown; Tika is the fallback.", "extraction.py"),
    ("Chunking & embedding", "Studio + model", "Chunks embedded then stored as SysEmbeddings.", "enrichment"),
    ("Document classification & field extraction", "Studio + model", "Typed fields written to OpenArch CinContext.", "fields.py"),
    ("Reranking", "Studio + model", "Cross-encoder reorders permitted candidates.", "rerank.py"),
    ("Embeddings inspection", "Studio", "Surfaces the stored vectors per chunk.", "/api/documents/{id}/embeddings"),
    ("Guided search interface", "Studio", "Keyword/HXQL/semantic in one surface.", "/api/search"),
    ("RAG orchestration & streaming chat", "Studio + model", "Grounded, cited answers over SSE.", "/api/chat"),
    ("Knowledge graph extraction & visualization", "Studio + model", "Typed entities & relations from enriched text.", "/api/graph"),
    ("Folder-scoped retrieval & graph", "Studio", "Scope search, chat & graph to one folder subtree.", "sys_ancestorIds"),
    ("Citations & retrieval trace", "Studio", "Every answer links to permitted sources.", "web/Ask"),
    ("AG-UI shaped event stream", "Studio", "Run, tool-call and message lifecycle events over SSE.", "/api/chat"),
    ("A2UI generative surfaces", "Studio", "Agent-composed UI rendered from the client's own catalog.", "/api/chat CUSTOM a2ui"),
    ("Deletion reflected in Q&A & graph", "Studio", "Removed documents leave retrieval and the graph.", "DELETE /api/documents/{id}"),
    ("Same-origin session gateway", "Studio", "Memory-only Basic-auth session.", "/api/session"),
]

_RUNTIMES = [
    {"name": "OpenArch", "role": "System of record (documents, ACLs, vectors)"},
    {"name": "Docling", "role": "Primary extraction: layout-aware text, tables & OCR"},
    {"name": "Apache Tika", "role": "Fallback text & metadata extraction"},
    {"name": "Ollama", "role": "Local embeddings & chat (OpenAI-compatible)"},
    {"name": "text-embeddings-inference", "role": "Reranking"},
    {"name": "Studio API", "role": "BFF, enrichment, agent orchestration"},
]


@router.get("/config")
async def config(request: Request) -> dict[str, Any]:
    """Client-readable runtime flags. Never gated, so the shell can adapt on load."""
    return {"baselineMode": bool(getattr(request.app.state, "baseline_mode", False))}


class ConfigUpdate(BaseModel):
    baselineMode: bool


@router.put("/config")
async def set_config(
    update: ConfigUpdate,
    request: Request,
    _credentials: Credentials = Depends(current_credentials),
) -> dict[str, Any]:
    """Flip baseline mode live (no restart). Requires a signed-in session."""
    request.app.state.baseline_mode = update.baselineMode
    return {"baselineMode": request.app.state.baseline_mode}


@router.get("/capabilities")
async def capabilities(request: Request) -> dict[str, Any]:
    baseline = bool(getattr(request.app.state, "baseline_mode", False))
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
