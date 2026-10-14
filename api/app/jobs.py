"""Enrichment job routes: list, manual trigger, and retry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from .auth import current_credentials, get_openarch_client
from .enrichment import EnrichmentService
from .models import Credentials
from .openarch import OpenArchClient

router = APIRouter(prefix="/api")


def get_enrichment(request: Request) -> EnrichmentService:
    return request.app.state.enrichment


@router.get("/jobs")
async def list_jobs(service: EnrichmentService = Depends(get_enrichment)) -> dict[str, Any]:
    return {"jobs": [job.to_dict() for job in service.store.list()]}


@router.post("/documents/{doc_id}/enrich", status_code=status.HTTP_202_ACCEPTED)
async def enrich_document(
    doc_id: str,
    background: BackgroundTasks,
    service: EnrichmentService = Depends(get_enrichment),
    credentials: Credentials = Depends(current_credentials),
    client: OpenArchClient = Depends(get_openarch_client),
) -> dict[str, Any]:
    doc = await client.get_document(doc_id)
    filename = doc.get("sys_name") or doc.get("sys_title") or doc_id
    job = service.store.create(doc_id, str(filename))
    background.add_task(service.run, job, credentials)
    return job.to_dict()


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(
    job_id: str,
    background: BackgroundTasks,
    service: EnrichmentService = Depends(get_enrichment),
    credentials: Credentials = Depends(current_credentials),
) -> dict[str, Any]:
    old = service.store.get(job_id)
    if old is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job = service.store.create(old.doc_id, old.filename)
    background.add_task(service.run, job, credentials)
    return job.to_dict()
