"""Library: browse, upload, inspect, permissions, and content download.

Upload creates an OpenArch SysFile, streams the binary into the upload area, and
attaches it. Enrichment (extraction/embedding) is a separate concern, started in
the enrichment module; this router only puts the source document into OpenArch.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel

from .acl import RuleIn, parse_access_field, to_sys_acl, validate_rules
from .auth import current_credentials, get_openarch_client
from .enrichment import EnrichmentService
from .models import Credentials
from .openarch import (
    ROOT_DOCUMENT_ID,
    OpenArchClient,
    OpenArchForbidden,
    OpenArchNotFound,
    OpenArchUnavailable,
)

router = APIRouter(prefix="/api")

# Extension -> MIME for the first-release supported formats.
SUPPORTED_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    # Scanned images — Tika (full/Tesseract) OCRs these into text.
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _document_type(doc: dict[str, Any]) -> str | None:
    props = doc.get("cinctx_contextProperties")
    value = props.get("document_type") if isinstance(props, dict) else None
    return value if isinstance(value, str) and value else None


def _own_access(perms: Any) -> str | None:
    granted = set(perms) if isinstance(perms, list) else set()
    if granted & {"ManageSecurity", "Everything"}:
        return "manage"
    if granted & {"Write", "ReadWrite"}:
        return "edit"
    return "read" if "Read" in granted else None


def _access(doc: dict[str, Any]) -> dict[str, Any]:
    """Access badges from what OpenArch returned; sys_effectiveAcl is only sent to managers."""
    acl = doc.get("sys_effectiveAcl")
    if not isinstance(acl, list):
        return {"mine": _own_access(doc.get("sys_effectivePermissions")), "sharedWith": None, "expiresAt": None}
    shared: list[dict[str, str]] = []
    ends: list[str] = []
    for ace in acl:
        if not isinstance(ace, dict) or ace.get("status") != "EFFECTIVE":
            continue
        if isinstance(ace.get("group"), dict):
            entry = {"kind": "group", "name": ace["group"].get("name") or ace["group"].get("id")}
        elif isinstance(ace.get("user"), dict):
            entry = {"kind": "user", "name": ace["user"].get("username") or ace["user"].get("id")}
        else:
            continue
        if entry["name"] and entry not in shared:
            shared.append(entry)
        if isinstance(ace.get("end"), str):
            ends.append(ace["end"])
    return {
        "mine": _own_access(doc.get("sys_effectivePermissions")),
        "sharedWith": shared,
        "expiresAt": min(ends, key=lambda e: datetime.fromisoformat(e.replace("Z", "+00:00"))) if ends else None,
    }


def summarize(doc: dict[str, Any]) -> dict[str, Any]:
    """Compact a DocumentDTO for list views; the inspector uses the raw document."""
    return {
        "id": doc.get("sys_id"),
        "title": doc.get("sys_title") or doc.get("sys_name"),
        "name": doc.get("sys_name"),
        "primaryType": doc.get("sys_primaryType"),
        "isFolderish": bool(doc.get("sys_isFolderish")),
        "modified": doc.get("sys_modified"),
        "mixinTypes": doc.get("sys_mixinTypes", []),
        "documentType": _document_type(doc),
        "parentId": doc.get("sys_parentId"),
        "access": _access(doc),
    }


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, OpenArchForbidden):
        return HTTPException(status_code=403, detail="Not permitted")
    if isinstance(exc, OpenArchNotFound):
        return HTTPException(status_code=404, detail="Not found")
    if isinstance(exc, OpenArchUnavailable):
        return HTTPException(status_code=503, detail="OpenArch is unreachable")
    return HTTPException(status_code=502, detail="OpenArch error")


@router.get("/documents")
async def list_documents(
    parentId: str = ROOT_DOCUMENT_ID,
    client: OpenArchClient = Depends(get_openarch_client),
) -> dict[str, Any]:
    try:
        result = await client.browse_children(parentId)
    except Exception as exc:  # noqa: BLE001 - mapped to HTTP below
        raise _translate(exc) from exc
    documents = [summarize(doc) for doc in result.get("documents", [])]
    return {"parentId": parentId, "documents": documents}


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: str,
    client: OpenArchClient = Depends(get_openarch_client),
) -> dict[str, Any]:
    try:
        return await client.get_document(doc_id)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: str,
    request: Request,
    client: OpenArchClient = Depends(get_openarch_client),
) -> None:
    """Delete from OpenArch and evict from the graph; retrieval excludes it automatically."""
    try:
        await client.delete_document(doc_id)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    request.app.state.graph.store.remove(doc_id)


@router.get("/documents/{doc_id}/acl")
async def get_document_acl(
    doc_id: str,
    usernames: str | None = None,
    client: OpenArchClient = Depends(get_openarch_client),
) -> dict[str, Any]:
    try:
        ids = [u for u in (usernames or "").split(",") if u]
        return await client.get_effective_acl(doc_id, ids or None)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc


@router.get("/documents/{doc_id}/embeddings")
async def get_document_embeddings(
    doc_id: str,
    raw: bool = False,
    client: OpenArchClient = Depends(get_openarch_client),
) -> dict[str, Any]:
    """The document's SysEmbeddings chunks: text + vector (with a small preview).

    With `raw=true`, returns the full SysEmbeddings records exactly as OpenArch's
    embeddings index returns them (vectors included) for inspection.
    """
    try:
        hits = await client.fetch_embeddings(doc_id)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    if raw:
        return {"docId": doc_id, "count": len(hits), "raw": hits}
    chunks = []
    for hit in hits:
        vector = hit.get("sysembed_vector") or []
        chunks.append(
            {
                "id": hit.get("sysembed_id"),
                "text": hit.get("sysembed_text") or "",
                "dims": len(vector),
                "preview": [round(float(v), 4) for v in vector[:24]],
            }
        )
    return {"docId": doc_id, "count": len(chunks), "embeddings": chunks}


@router.get("/documents/{doc_id}/content")
async def get_document_content(
    doc_id: str,
    client: OpenArchClient = Depends(get_openarch_client),
) -> Response:
    try:
        content, content_type = await client.download(doc_id)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    return Response(content=content, media_type=content_type)


# Browser-displayable image formats; others (TIFF, BMP) are converted for preview.
_WEB_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@router.get("/documents/{doc_id}/preview")
async def get_document_preview(
    doc_id: str,
    client: OpenArchClient = Depends(get_openarch_client),
) -> Response:
    """A browser-renderable image for the inspector: TIFF/BMP are converted to PNG."""
    try:
        content, content_type = await client.download(doc_id)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc

    if content_type.startswith("image/") and content_type not in _WEB_IMAGE_TYPES:
        from io import BytesIO

        from PIL import Image

        image = Image.open(BytesIO(content))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return Response(content=buffer.getvalue(), media_type="image/png")

    return Response(content=content, media_type=content_type)


class FolderIn(BaseModel):
    title: str | None = None
    access: list[RuleIn] | None = None


def _create_error(exc: Exception, with_access: bool) -> HTTPException:
    if with_access and isinstance(exc, OpenArchForbidden):
        return HTTPException(status_code=403, detail="You can't set access in this folder")
    return _translate(exc)


@router.post("/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: FolderIn,
    parentId: str = ROOT_DOCUMENT_ID,
    client: OpenArchClient = Depends(get_openarch_client),
) -> dict[str, Any]:
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Folder name is required")
    payload: dict[str, Any] = {"sys_primaryType": "SysFolder", "sys_title": title, "sys_name": title}
    if body.access is not None:
        validate_rules(body.access, datetime.now(timezone.utc))
        payload["sys_acl"] = to_sys_acl(body.access)
    try:
        return await client.create_document(parentId, payload)
    except Exception as exc:  # noqa: BLE001
        raise _create_error(exc, body.access is not None) from exc


@router.post("/documents/{doc_id}/move")
async def move_document(
    doc_id: str,
    body: dict[str, Any],
    client: OpenArchClient = Depends(get_openarch_client),
) -> dict[str, Any]:
    """Reparent a document under another folder (native OpenArch move)."""
    target = str(body.get("targetParentId") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="targetParentId is required")
    try:
        await client.move_document(doc_id, target)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    return {"ok": True, "docId": doc_id, "targetParentId": target}


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    background: BackgroundTasks,
    request: Request,
    parentId: str = ROOT_DOCUMENT_ID,
    access: str | None = Form(None),
    client: OpenArchClient = Depends(get_openarch_client),
    credentials: Credentials = Depends(current_credentials),
) -> dict[str, Any]:
    rules = parse_access_field(access)
    if rules is not None:
        validate_rules(rules, datetime.now(timezone.utc))
    filename = file.filename or "upload.bin"
    extension = os.path.splitext(filename)[1].lower()
    if extension not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {extension or 'unknown'}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # Auto-start enrichment: a successful upload begins extraction/embedding in the background.
    # Baseline mode keeps the app to native OpenArch only: store the SysFile, skip enrichment.
    baseline = getattr(request.app.state, "baseline_mode", False)
    try:
        return await store_and_enrich(
            client,
            parentId,
            filename,
            content,
            credentials,
            background,
            rules,
            service=None if baseline else request.app.state.enrichment,
        )
    except Exception as exc:  # noqa: BLE001
        raise _create_error(exc, rules is not None) from exc


async def store_and_enrich(
    client: OpenArchClient,
    parent_id: str,
    filename: str,
    content: bytes,
    owner: Credentials,
    background: BackgroundTasks,
    access: list[RuleIn] | None = None,
    *,
    service: EnrichmentService | None,
) -> dict[str, Any]:
    """Create a SysFile from `content`; with a service, start enrichment in the background.

    OpenArch errors propagate unchanged; callers translate them.
    """
    mime = SUPPORTED_TYPES[os.path.splitext(filename)[1].lower()]
    payload: dict[str, Any] = {
        "sys_primaryType": "SysFile",
        "sys_title": filename,
        "sys_name": filename,
    }
    if access is not None:
        payload["sys_acl"] = to_sys_acl(access)
    payload["sysfile_blob"] = {"uploadId": await client.upload_binary(filename, mime, content)}
    created = await client.create_document(parent_id, payload)
    doc_id = created["sys_id"]
    document = await client.get_document(doc_id)
    if service is None:
        return document
    job = service.store.create(doc_id, filename, owner.username)
    background.add_task(service.run, job, owner, content=content, mime=mime)
    document["_studioJobId"] = job.id
    return document
