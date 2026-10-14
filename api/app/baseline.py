"""Baseline mode: a single switch that disables every Studio extension so the
app presents only what OpenArch provides out of the box.

When `STUDIO_BASELINE_MODE=true`, the AI/enrichment surfaces (guided search,
grounded chat, knowledge graph, enrichment jobs) are turned off and uploads
store the native SysFile without extraction or embedding. Native OpenArch —
storage, folders, ACLs, HXQL, SysEmbeddings vector search, users/groups —
stays fully available.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status


def extensions_disabled(request: Request) -> bool:
    return bool(getattr(request.app.state.settings, "baseline_mode", False))


async def require_extensions(request: Request) -> None:
    """Router dependency: 403 every extension route while baseline mode is on."""
    if extensions_disabled(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Studio extensions are disabled — baseline mode (OpenArch OOTB only).",
        )
