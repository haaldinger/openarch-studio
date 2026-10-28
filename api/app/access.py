"""Readable permissions: a document's rules (local + inherited), effective access, principal search."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import Session, current_session, get_openarch_client
from .demo import DemoUsers
from .library import _translate
from .openarch import (
    ROOT_DOCUMENT_ID,
    OpenArchClient,
    OpenArchError,
    OpenArchForbidden,
    OpenArchNotFound,
)

router = APIRouter(prefix="/api")

_MAX_ANCESTOR_HOPS = 20
_MAX_PRINCIPALS = 20


def _principal(ace: dict[str, Any]) -> dict[str, Any] | None:
    user = ace.get("user")
    if isinstance(user, dict):
        return {"kind": "user", "id": user.get("id"), "name": user.get("username")}
    group = ace.get("group")
    if isinstance(group, dict):
        return {"kind": "group", "id": group.get("id"), "name": group.get("name")}
    return None


def _rules(doc: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    source = {"kind": kind, "id": doc.get("sys_id"), "title": doc.get("sys_title")}
    rules = []
    for ace in doc.get("sys_acl") or []:
        principal = _principal(ace)
        if principal is None:
            continue
        rules.append(
            {
                "principal": principal,
                "permission": ace.get("permission"),
                "granted": ace.get("granted", True),
                "begin": ace.get("begin"),
                "end": ace.get("end"),
                "status": ace.get("status"),
                "source": source,
            }
        )
    return rules


async def _inherited_rules(client: OpenArchClient, doc: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    parent_id = doc.get("sys_parentId")
    for _ in range(_MAX_ANCESTOR_HOPS):
        if not parent_id or parent_id == ROOT_DOCUMENT_ID:
            break
        try:
            ancestor = await client.get_document(parent_id)
        except (OpenArchForbidden, OpenArchNotFound):
            break  # an unreadable ancestor hides its own parent link too
        rules.extend(_rules(ancestor, "inherited"))
        parent_id = ancestor.get("sys_parentId")
    return rules


async def _effective(
    client: OpenArchClient, doc_id: str, session: Session, demo: DemoUsers | None
) -> list[dict[str, Any]]:
    if demo is not None:
        subjects = {p.user_id: p for p in demo.personas.values()}
        names = {uid: p.username for uid, p in subjects.items()}
        labels = {uid: p.label for uid, p in subjects.items()}
    else:
        username = session.active.username
        matches = [u for u in await client.find_users(username) if u.get("username") == username]
        if not matches:
            return []
        names = {matches[0]["id"]: username}
        labels = {}
    result = await client.get_effective_permissions(doc_id, list(names))
    effective = []
    for entry in result.get("fullEffectivePermissions") or []:
        user_id = entry.get("userId")
        row: dict[str, Any] = {
            "userId": user_id,
            "username": names.get(user_id, user_id),
            "permissions": entry.get("userPermissions") or [],
        }
        if user_id in labels:
            row["label"] = labels[user_id]
        effective.append(row)
    return effective


@router.get("/documents/{doc_id}/access")
async def get_access(
    doc_id: str,
    request: Request,
    session: Session = Depends(current_session),
    client: OpenArchClient = Depends(get_openarch_client),
) -> dict[str, Any]:
    demo: DemoUsers | None = getattr(request.app.state, "demo", None)
    try:
        doc = await client.get_document(doc_id)
        can_manage = "sys_acl" in doc
        rules: list[dict[str, Any]] = []
        if can_manage:
            rules = _rules(doc, "local") + await _inherited_rules(client, doc)
        effective = await _effective(client, doc_id, session, demo)
    except OpenArchError as exc:
        raise _translate(exc) from exc
    return {"canManage": can_manage, "rules": rules, "effective": effective}


@router.get("/principals")
async def search_principals(
    request: Request,
    q: str = "",
    client: OpenArchClient = Depends(get_openarch_client),
) -> list[dict[str, Any]]:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Enter a name to search")
    demo: DemoUsers | None = getattr(request.app.state, "demo", None)
    try:
        users = await client.find_users(query)
        groups = await client.find_groups(query)
    except OpenArchError as exc:
        raise _translate(exc) from exc
    results: list[dict[str, Any]] = []
    for user in users:
        row: dict[str, Any] = {"kind": "user", "id": user.get("id"), "name": user.get("username")}
        persona = demo.personas.get(user.get("username")) if demo is not None else None
        if persona is not None:
            row["label"] = persona.label
        results.append(row)
    results.extend({"kind": "group", "id": g.get("id"), "name": g.get("name")} for g in groups)
    return results[:_MAX_PRINCIPALS]
