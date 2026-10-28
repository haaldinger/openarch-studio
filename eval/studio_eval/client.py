"""Studio HTTP client and AG-UI chat stream parser."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT_ID = "00000000-0000-0000-0000-000000000000"
CHAT_READ_TIMEOUT_S = 300.0
MISSING_JOB_POLLS = 3
_RERUN_HINT = "Delete it from the Eval corpus folder and re-run."


class StudioError(Exception):
    pass


@dataclass
class Citation:
    doc_id: str
    title: str
    page: int
    snippet: str
    score: float | None
    vector_score: float | None


@dataclass
class ChatResult:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    rerank: str | None = None
    error: str | None = None


def parse_chat_stream(lines: Iterable[str]) -> ChatResult:
    result = ChatResult(answer="", citations=[])
    finished = False
    for line in lines:
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "TEXT_MESSAGE_CONTENT":
            result.answer += event.get("delta") or ""
        elif kind == "TOOL_CALL_END":
            result.rerank = (event.get("result") or {}).get("rerank")
        elif kind == "STATE_SNAPSHOT":
            for c in (event.get("snapshot") or {}).get("citations", []):
                result.citations.append(
                    Citation(
                        doc_id=c["docId"],
                        title=c.get("title") or c["docId"],
                        page=c.get("page") or 1,
                        snippet=c.get("snippet") or "",
                        score=c.get("score"),
                        vector_score=c.get("vectorScore"),
                    )
                )
        elif kind == "RUN_ERROR":
            finished = True
            result.error = event.get("message") or "run error"
        elif kind == "RUN_FINISHED":
            finished = True
    if not finished:
        result.error = "stream ended without RUN_FINISHED"
    return result


class StudioClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._user = user
        self._password = password
        self._sleep = sleep
        self._clock = clock
        self._http = httpx.Client(base_url=self.base_url, timeout=30.0)

    def __enter__(self) -> StudioClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    def _transport_error(self, exc: httpx.TransportError) -> StudioError:
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return StudioError(f"cannot reach Studio at {self.base_url}")
        return StudioError(f"Studio request failed: {type(exc).__name__}: {exc}")

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            raise self._transport_error(exc) from None
        if response.status_code == 401:
            raise StudioError("not signed in / sign-in expired")
        if response.status_code >= 400:
            raise StudioError(f"{method} {url} failed: HTTP {response.status_code}")
        return response

    def login(self) -> None:
        try:
            response = self._http.post(
                "/api/session", json={"username": self._user, "password": self._password}
            )
        except httpx.TransportError as exc:
            raise self._transport_error(exc) from None
        if response.status_code == 401:
            raise StudioError(f"sign-in failed for user {self._user}")
        if response.status_code >= 400:
            raise StudioError(f"sign-in failed: HTTP {response.status_code}")

    def _children(self, parent_id: str) -> list[dict[str, Any]]:
        response = self._request("GET", "/api/documents", params={"parentId": parent_id})
        return _json(response).get("documents", [])

    def ensure_folder(self, title: str) -> str:
        for doc in self._children(ROOT_ID):
            if doc.get("isFolderish") and doc.get("title") == title:
                return doc["id"]
        response = self._request("POST", "/api/folders", json={"title": title})
        return _json(response)["sys_id"]

    def ensure_corpus(
        self,
        folder_id: str,
        samples_dir: Path,
        timeout_s: float = 900,
        poll_s: float = 5,
    ) -> dict[str, str]:
        samples_dir = Path(samples_dir)
        if not samples_dir.is_dir():
            raise StudioError(f"samples directory not found: {samples_dir}")
        present = {d.get("name") or d.get("title"): d["id"] for d in self._children(folder_id)}
        corpus: dict[str, str] = {}
        pending: dict[str, str] = {}  # job id -> file name
        for path in sorted(p for p in samples_dir.iterdir() if p.is_file()):
            if path.name in present:
                corpus[path.name] = present[path.name]
                continue
            response = self._request(
                "POST",
                "/api/documents",
                params={"parentId": folder_id},
                files={"file": (path.name, path.read_bytes())},
            )
            doc = _json(response)
            corpus[path.name] = doc["sys_id"]
            if doc.get("_studioJobId"):
                pending[doc["_studioJobId"]] = path.name
        self._wait_for_jobs(pending, timeout_s, poll_s)
        return corpus

    def _wait_for_jobs(self, pending: dict[str, str], timeout_s: float, poll_s: float) -> None:
        if not pending:
            return
        start = self._clock()
        missing: dict[str, int] = {}
        while True:
            jobs = {j["id"]: j for j in _json(self._request("GET", "/api/jobs")).get("jobs", [])}
            for job_id, name in list(pending.items()):
                job = jobs.get(job_id)
                if job is None:
                    missing[job_id] = missing.get(job_id, 0) + 1
                    if missing[job_id] >= MISSING_JOB_POLLS:
                        raise StudioError(
                            f"enrichment job for {name} disappeared — was studio-api restarted? "
                            f"{_RERUN_HINT}"
                        )
                    continue
                missing.pop(job_id, None)
                if job["state"] == "complete":
                    del pending[job_id]
                elif job["state"] == "failed":
                    raise StudioError(f"enrichment failed for {name}: {_failure(job)}. {_RERUN_HINT}")
            if not pending:
                return
            if self._clock() - start >= timeout_s:
                names = ", ".join(sorted(pending.values()))
                raise StudioError(
                    f"enrichment timed out after {timeout_s:g}s; pending: {names}. {_RERUN_HINT}"
                )
            self._sleep(poll_s)

    def ask(self, question: str, scope: str) -> ChatResult:
        timeout = httpx.Timeout(30.0, read=CHAT_READ_TIMEOUT_S)
        try:
            with self._http.stream(
                "POST", "/api/chat", json={"question": question, "scope": scope}, timeout=timeout
            ) as response:
                if response.status_code == 401:
                    raise StudioError("not signed in / sign-in expired")
                if response.status_code == 403:
                    raise StudioError("Ask is disabled — is Studio in baseline mode?")
                if response.status_code >= 400:
                    raise StudioError(f"POST /api/chat failed: HTTP {response.status_code}")
                return parse_chat_stream(response.iter_lines())
        except httpx.TransportError as exc:
            raise self._transport_error(exc) from None

    def extracted_text(self, doc_id: str) -> dict[int, str]:
        response = self._request("GET", f"/api/documents/{doc_id}/embeddings", params={"raw": "true"})
        pages: dict[int, list[str]] = {}
        for hit in _json(response).get("raw", []):
            page = ((hit.get("sysembed_location") or {}).get("text") or {}).get("page")
            page = page if isinstance(page, int) and page > 0 else 1
            pages.setdefault(page, []).append(hit.get("sysembed_text") or "")
        return {p: "\n\n".join(texts) for p, texts in sorted(pages.items())}


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise StudioError(f"unexpected response from {response.request.url.path}") from None


def _failure(job: dict[str, Any]) -> str:
    stage = next((s for s in job.get("stages", []) if s.get("status") == "failed"), None)
    if stage:
        return f"stage '{stage['name']}': {stage.get('detail') or 'no detail'}"
    return job.get("error") or "unknown error"
