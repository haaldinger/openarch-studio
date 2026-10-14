"""Enrichment pipeline: extract (Tika) -> chunk -> embed -> SysEmbeddings child.

Jobs run as FastAPI background tasks against an in-memory store. Active job
history is transient (a restart clears it); durable readiness is reconstructed
from the source document's SysHasEmbeddings mixin and its SysEmbeddings children
in OpenArch. Enrichment always re-reads the source binary from OpenArch, so a
retry needs nothing kept in Studio.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .models import Credentials
from .openarch import OpenArchClient
from .parquet import EmbeddedChunk, chunk_text, normalize_vector, write_embeddings

if False:  # typing-only import to avoid a runtime cycle
    from .graph import GraphService

STAGES = ["stored", "extracted", "chunked", "embedded", "indexed"]
_PARQUET_MIME = "application/x-parquet"


@dataclass
class Stage:
    name: str
    status: str = "pending"  # pending | running | done | failed
    detail: str = ""


@dataclass
class Job:
    id: str
    doc_id: str
    filename: str
    state: str = "running"  # running | complete | failed
    stages: list[Stage] = field(default_factory=lambda: [Stage(n) for n in STAGES])
    error: str | None = None
    created: float = field(default_factory=time.time)

    def stage(self, name: str) -> Stage:
        return next(s for s in self.stages if s.name == name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "docId": self.doc_id,
            "filename": self.filename,
            "state": self.state,
            "error": self.error,
            "stages": [{"name": s.name, "status": s.status, "detail": s.detail} for s in self.stages],
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, doc_id: str, filename: str) -> Job:
        job = Job(id=str(uuid.uuid4()), doc_id=doc_id, filename=filename)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)


class EnrichmentService:
    def __init__(
        self, settings: Settings, store: JobStore | None = None, graph: "GraphService | None" = None
    ) -> None:
        self._settings = settings
        self.store = store or JobStore()
        self._graph = graph
        # Bounds concurrent OCR/embedding work across a batch upload.
        self._sem = asyncio.Semaphore(max(1, settings.enrich_concurrency))

    def embedding_type(self) -> str:
        label = re.sub(r"[^A-Za-z0-9_-]", "-", self._settings.embedding_model)
        return label[:200]

    async def extract_text(self, content: bytes, mime: str) -> str:
        return await self._extract(content, mime)

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string and normalize it to the stored vector width."""
        vector = (await self._embed([text]))[0]
        return normalize_vector(vector)

    async def _extract(self, content: bytes, mime: str) -> str:
        url = f"{self._settings.tika_url}/tika"
        # OCR of large scanned images is slow; allow generous time.
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.put(
                url, content=content, headers={"Accept": "text/plain", "Content-Type": mime}
            )
            response.raise_for_status()
            return response.text

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        url = f"{self._settings.model_base_url}/embeddings"
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url, json={"model": self._settings.embedding_model, "input": texts}
            )
            response.raise_for_status()
            data = response.json()["data"]
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(texts):
            raise ValueError("embedding provider returned a mismatched number of vectors")
        return vectors

    async def run(
        self,
        job: Job,
        credentials: Credentials,
        *,
        content: bytes | None = None,
        mime: str = "application/octet-stream",
    ) -> Job:
        client = OpenArchClient(self._settings.openarch_url, credentials)
        try:
            async with self._sem:
                await self._run_pipeline(job, client, content, mime)
        except Exception as exc:  # noqa: BLE001 - recorded on the failing stage
            current = next((s for s in job.stages if s.status == "running"), None)
            if current is not None:
                current.status = "failed"
                current.detail = str(exc) or type(exc).__name__
            job.state = "failed"
            job.error = str(exc) or type(exc).__name__
        return job

    async def _run_pipeline(
        self, job: Job, client: OpenArchClient, content: bytes | None, mime: str
    ) -> None:
        # stored: the source binary already lives in OpenArch.
        if content is None:
            content, mime = await client.download(job.doc_id)
        job.stage("stored").status = "done"

        running = job.stage("extracted")
        running.status = "running"
        text = await self._extract(content, mime)
        running.status = "done"
        running.detail = f"{len(text)} chars"

        chunking = job.stage("chunked")
        chunking.status = "running"
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("no extractable text to chunk")
        chunking.status = "done"
        chunking.detail = f"{len(chunks)} chunks"

        embedding = job.stage("embedded")
        embedding.status = "running"
        vectors = await self._embed([c.text for c in chunks])
        embedded = [
            EmbeddedChunk(
                id=c.id,
                text=c.text,
                vector=normalize_vector(v),
                page=c.page,
                paragraph=c.paragraph,
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        blob = write_embeddings(embedded, self.embedding_type())
        await client.ensure_has_embeddings_mixin(job.doc_id)
        upload_id = await client.upload_binary(f"{job.filename}.parquet", _PARQUET_MIME, blob)
        await client.create_document(
            job.doc_id,
            {
                "sys_primaryType": "SysEmbeddings",
                "sys_name": f"_e_{self.embedding_type()}",
                "sys_title": "Studio embeddings",
                "sysemb_embeddings": {"uploadId": upload_id},
            },
        )
        embedding.status = "done"
        embedding.detail = f"{len(embedded)} vectors"

        indexing = job.stage("indexed")
        indexing.status = "running"
        await client.wait_for_indexing()
        indexing.status = "done"

        job.state = "complete"

        # Knowledge graph is additive: extract from the same text, never fail the job on it.
        if self._graph is not None:
            try:
                await self._graph.extract(job.doc_id, text)
            except Exception:  # noqa: BLE001
                pass
