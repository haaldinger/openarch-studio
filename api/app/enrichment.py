"""Enrichment pipeline: extract (Docling, Tika fallback) -> chunk -> embed -> SysEmbeddings child.

Jobs run as FastAPI background tasks against an in-memory store. Active job
history is transient (a restart clears it); durable readiness is reconstructed
from the source document's SysHasEmbeddings mixin and its SysEmbeddings children
in OpenArch. Enrichment always re-reads the source binary from OpenArch, so a
retry needs nothing kept in Studio.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .extraction import Extracted, build_extractor
from .models import Credentials
from .openarch import OpenArchClient, OpenArchForbidden
from .parquet import EmbeddedChunk, chunk_pages, normalize_vector, write_embeddings

if False:  # typing-only import to avoid a runtime cycle
    from .fields import FieldsService
    from .graph import GraphService

STAGES = ["stored", "extracted", "chunked", "embedded", "indexed", "classified"]
_PARQUET_MIME = "application/x-parquet"
log = logging.getLogger(__name__)


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
    owner: str  # username of the identity that started the job
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

    def create(self, doc_id: str, filename: str, owner: str) -> Job:
        job = Job(id=str(uuid.uuid4()), doc_id=doc_id, filename=filename, owner=owner)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_for(self, owner: str) -> list[Job]:
        jobs = [j for j in self._jobs.values() if j.owner == owner]
        return sorted(jobs, key=lambda j: j.created, reverse=True)


class EnrichmentService:
    def __init__(
        self,
        settings: Settings,
        store: JobStore | None = None,
        graph: "GraphService | None" = None,
        extractor: Any = None,
        fields: "FieldsService | None" = None,
    ) -> None:
        self._settings = settings
        self.store = store or JobStore()
        self._graph = graph
        self._fields = fields
        self._extractor = extractor or build_extractor(settings)
        # Bounds concurrent OCR/embedding work across a batch upload.
        self._sem = asyncio.Semaphore(max(1, settings.enrich_concurrency))

    def embedding_type(self) -> str:
        label = re.sub(r"[^A-Za-z0-9_-]", "-", self._settings.embedding_model)
        return label[:200]

    async def extract_text(self, content: bytes, mime: str) -> str:
        return (await self._extractor.extract(content, mime, "document")).markdown

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string and normalize it to the stored vector width."""
        vector = (await self._embed([text]))[0]
        return normalize_vector(vector)

    def _extracted_detail(self, extracted: Extracted) -> str:
        n = len(extracted.markdown)
        if extracted.engine == "docling":
            return f"Docling · {n} chars"
        if self._settings.extractor == "tika":
            return f"Tika · {n} chars"
        return f"Tika fallback · {n} chars"

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
        extracted = await self._extractor.extract(content, mime, job.filename)
        running.status = "done"
        running.detail = self._extracted_detail(extracted)

        chunking = job.stage("chunked")
        chunking.status = "running"
        chunks = chunk_pages(extracted.pages)
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
        created = await client.create_document(
            job.doc_id,
            {
                "sys_primaryType": "SysEmbeddings",
                "sys_name": f"_e_{self.embedding_type()}",
                "sys_title": "Studio embeddings",
                "sysemb_embeddings": {"uploadId": upload_id},
            },
        )
        await self._delete_stale_embeddings(client, job.doc_id, created.get("sys_id"))
        embedding.status = "done"
        embedding.detail = f"{len(embedded)} vectors"

        indexing = job.stage("indexed")
        indexing.status = "running"
        await client.wait_for_indexing()
        indexing.status = "done"

        job.state = "complete"

        await self._classify(job, client, extracted.markdown)

        # Knowledge graph is additive: extract from the same text, never fail the job on it.
        if self._graph is not None:
            try:
                await self._graph.extract(job.doc_id, extracted.markdown)
            except Exception:  # noqa: BLE001
                pass

    async def _delete_stale_embeddings(
        self, client: OpenArchClient, doc_id: str, keep_id: str | None
    ) -> None:
        """Re-enrichment replaces embeddings; a failed cleanup is logged, never fatal."""
        if not keep_id:
            return
        try:
            stale = [i for i in await client.list_embedding_child_ids(doc_id) if i != keep_id]
        except Exception:  # noqa: BLE001
            log.warning("could not list stale embeddings for %s", doc_id, exc_info=True)
            return
        for child_id in stale:
            try:
                await client.delete_document(child_id)
            except Exception:  # noqa: BLE001
                log.warning("could not delete stale embeddings %s", child_id, exc_info=True)

    async def _classify(self, job: Job, client: OpenArchClient, markdown: str) -> None:
        """Additive stage: failures are recorded on the stage, never on the job."""
        stage = job.stage("classified")
        if self._fields is None:
            stage.status = "done"
            stage.detail = "skipped"
            return
        stage.status = "running"
        try:
            vocabulary = await self._fields.vocabulary(client)
            result = await self._fields.classify(markdown, vocabulary)
            await self._fields.store(client, job.doc_id, result)
        except OpenArchForbidden:
            stage.status = "failed"
            stage.detail = "no write permission on this document"
        except Exception as exc:  # noqa: BLE001 - includes ValueError and httpx errors
            stage.status = "failed"
            stage.detail = str(exc) or type(exc).__name__
        else:
            stage.status = "done"
            stage.detail = f"{result.document_type} · {len(result.fields)} fields"
