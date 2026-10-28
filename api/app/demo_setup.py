"""One-click demo setup and reset: permission-separated folders plus synthetic sample documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status

from .acl import Principal, RuleIn, to_sys_acl
from .auth import origin_credentials, require_demo_admin
from .config import Settings
from .demo import DemoUsers
from .library import SUPPORTED_TYPES, _translate, store_and_enrich
from .models import Credentials
from .openarch import ROOT_DOCUMENT_ID, OpenArchClient

router = APIRouter(prefix="/api/demo")

DEMO_FOLDER = "Studio Demo"
# Demo folder -> group that can read it; the root demo folder is readable by `members`.
FOLDER_GROUPS = {"Company": "members", "Finance": "finance", "HR": "hr", "Sales": "sales"}
# Document-level Read granted to a persona on one sample (the live time limit is added by hand).
PERSONA_READS = {("Sales", "q4-pricing.md"): "cory"}


def _group_read(demo: DemoUsers, group: str) -> list[RuleIn]:
    return [RuleIn(principal=Principal(kind="group", id=demo.group_ids[group]), permission="Read")]


async def _find_child(client: OpenArchClient, parent_id: str, title: str) -> str | None:
    result = await client.browse_children(parent_id)
    for doc in result.get("documents", []):
        if doc.get("sys_title") == title:
            return doc["sys_id"]
    return None


async def _ensure_folder(
    client: OpenArchClient, parent_id: str, title: str, rules: list[RuleIn]
) -> str:
    existing = await _find_child(client, parent_id, title)
    if existing is not None:
        return existing
    created = await client.create_document(
        parent_id,
        {
            "sys_primaryType": "SysFolder",
            "sys_title": title,
            "sys_name": title,
            "sys_acl": to_sys_acl(rules),
        },
    )
    return created["sys_id"]


def _samples_dir(settings: Settings) -> Path:
    path = Path(settings.demo_samples_dir) if settings.demo_samples_dir else None
    if path is None or not path.is_dir():
        raise HTTPException(
            status_code=500,
            detail="Demo samples not found (set STUDIO_DEMO_SAMPLES_DIR)",
        )
    return path


@router.post("/setup")
async def setup_demo(
    request: Request,
    background: BackgroundTasks,
    demo: DemoUsers = Depends(require_demo_admin),
    origin: Credentials = Depends(origin_credentials),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    samples = _samples_dir(settings)
    # The signed-in admin does the setup, even while acting as a persona.
    client = OpenArchClient(settings.openarch_url, origin)
    service = None if getattr(request.app.state, "baseline_mode", False) else request.app.state.enrichment

    folders: dict[str, str] = {}
    jobs: list[str] = []
    try:
        root = await _ensure_folder(client, ROOT_DOCUMENT_ID, DEMO_FOLDER, _group_read(demo, "members"))
        folders[DEMO_FOLDER] = root
        for name, group in FOLDER_GROUPS.items():
            folder_id = await _ensure_folder(client, root, name, _group_read(demo, group))
            folders[name] = folder_id
            existing = {
                d.get("sys_title") for d in (await client.browse_children(folder_id)).get("documents", [])
            }
            for path in sorted((samples / name).glob("*")):
                if path.name in existing or path.suffix.lower() not in SUPPORTED_TYPES:
                    continue
                reader = PERSONA_READS.get((name, path.name))
                access = (
                    [
                        RuleIn(
                            principal=Principal(kind="user", id=demo.personas[reader].user_id),
                            permission="Read",
                        )
                    ]
                    if reader
                    else None
                )
                document = await store_and_enrich(
                    client, folder_id, path.name, path.read_bytes(), origin, background, access,
                    service=service,
                )
                if "_studioJobId" in document:
                    jobs.append(document["_studioJobId"])
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    return {"folders": folders, "jobs": jobs}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_demo(
    request: Request,
    _demo: DemoUsers = Depends(require_demo_admin),
    origin: Credentials = Depends(origin_credentials),
) -> Response:
    settings: Settings = request.app.state.settings
    client = OpenArchClient(settings.openarch_url, origin)
    try:
        root = await _find_child(client, ROOT_DOCUMENT_ID, DEMO_FOLDER)
        if root is not None:
            graph = request.app.state.graph.store
            for folder in (await client.browse_children(root)).get("documents", []):
                for doc in (await client.browse_children(folder["sys_id"])).get("documents", []):
                    graph.remove(doc["sys_id"])
            await client.delete_document(root)
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
