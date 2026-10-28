"""Typed OpenArch REST client.

One instance wraps one caller's credentials, so every call this client makes is
authorized as that user — the mechanism that keeps OpenArch ACLs in force across
the whole Studio workflow. Transport and status failures are mapped to a small
set of typed errors the route layer translates to HTTP responses.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from .models import Credentials

ROOT_DOCUMENT_ID = "00000000-0000-0000-0000-000000000000"
_REPOSITORY_HEADER = "HXCS-Repository"


class OpenArchError(Exception):
    """Base class for OpenArch client failures."""


class OpenArchAuthError(OpenArchError):
    """Credentials were rejected (HTTP 401)."""


class OpenArchForbidden(OpenArchError):
    """Authenticated but not allowed (HTTP 403)."""


class OpenArchNotFound(OpenArchError):
    """Target does not exist, or is not visible to this caller (HTTP 404)."""


class OpenArchUnavailable(OpenArchError):
    """OpenArch could not be reached, or returned a server error."""


class OpenArchClient:
    def __init__(
        self,
        base_url: str,
        credentials: Credentials,
        *,
        repository: str = "default",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._credentials = credentials
        self._repository = repository
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {_REPOSITORY_HEADER: self._repository}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._base_url}{path}"
        auth = self._credentials.basic_auth()
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        try:
            if self._client is not None:
                response = await self._client.request(
                    method, url, auth=auth, headers=headers, **kwargs
                )
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.request(
                        method, url, auth=auth, headers=headers, **kwargs
                    )
        except httpx.HTTPError as exc:
            raise OpenArchUnavailable(str(exc)) from exc

        if response.status_code == 401:
            raise OpenArchAuthError(path)
        if response.status_code == 403:
            raise OpenArchForbidden(path)
        if response.status_code == 404:
            raise OpenArchNotFound(path)
        if response.status_code >= 500:
            raise OpenArchUnavailable(f"{path} -> HTTP {response.status_code}")
        return response

    async def authenticate(self) -> str:
        """Validate credentials against the repository root; return the username.

        A 403 on root means the credentials are valid but the user cannot read root.
        """
        try:
            await self._request("GET", f"/api/documents/{ROOT_DOCUMENT_ID}")
        except OpenArchForbidden:
            pass
        return self._credentials.username

    async def get_document(self, doc_id: str) -> dict[str, Any]:
        response = await self._request("GET", f"/api/documents/{doc_id}")
        return response.json()

    async def query(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("POST", "/api/query", json=payload)
        return response.json()

    async def browse_children(self, parent_id: str, *, limit: int = 100) -> dict[str, Any]:
        """List documents directly under a parent folder."""
        payload = {
            "query": (
                "SELECT * FROM SysContent "
                f"WHERE sys_parentId = '{parent_id}' ORDER BY sys_title"
            ),
            "limit": limit,
            "offset": 0,
        }
        return await self.query(payload)

    async def create_document(self, parent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("POST", f"/api/documents/{parent_id}", json=payload)
        return response.json()

    async def update_document(self, doc_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("PUT", f"/api/documents/{doc_id}", json=payload)
        return response.json()

    async def delete_document(self, doc_id: str) -> None:
        await self._request("DELETE", f"/api/documents/{doc_id}")

    async def move_document(self, doc_id: str, target_parent_id: str) -> None:
        """Reparent a document under a new folder (native OpenArch move)."""
        await self._request(
            "POST", f"/api/documents/{doc_id}/move", json={"targetParentId": target_parent_id}
        )

    async def upload_binary(self, filename: str, mime_type: str, content: bytes) -> str:
        """Stream a binary into OpenArch's upload area; return its upload id."""
        params = {"fileName": filename, "mimeType": mime_type}
        response = await self._request(
            "POST",
            "/api/upload",
            params=params,
            content=content,
            headers={"Content-Type": mime_type},
        )
        return response.json()["id"]

    async def get_effective_acl(
        self, doc_id: str, user_ids: list[str] | None = None
    ) -> dict[str, Any]:
        params = {"usernames": ",".join(user_ids)} if user_ids else None
        response = await self._request(
            "GET", f"/api/documents/{doc_id}/fulleffectiveacl", params=params
        )
        return response.json()

    async def get_effective_permissions(
        self, doc_id: str, user_ids: list[str]
    ) -> dict[str, Any]:
        # OpenArch's `usernames` parameter takes user ids, not names.
        response = await self._request(
            "GET",
            f"/api/documents/{doc_id}/fulleffectivepermissions",
            params={"usernames": ",".join(user_ids)},
        )
        return response.json()

    async def find_users(self, name: str) -> list[dict[str, Any]]:
        response = await self._request("GET", "/api/user", params={"name": name})
        return response.json()

    async def find_groups(self, name: str) -> list[dict[str, Any]]:
        response = await self._request("GET", "/api/group", params={"name": name})
        return response.json()

    async def download(self, doc_id: str, xpath: str = "sysfile_blob") -> tuple[bytes, str]:
        response = await self._request("GET", f"/api/download/{doc_id}/{xpath}")
        return response.content, response.headers.get("content-type", "application/octet-stream")

    async def ensure_mixin(self, doc_id: str, mixin: str) -> None:
        doc = await self.get_document(doc_id)
        mixins = list(doc.get("sys_mixinTypes") or [])
        if mixin in mixins:
            return
        mixins.append(mixin)
        await self.update_document(doc_id, {"sys_mixinTypes": mixins})

    async def ensure_has_embeddings_mixin(self, doc_id: str) -> None:
        """Add the SysHasEmbeddings mixin a parent needs before it can hold a SysEmbeddings child."""
        await self.ensure_mixin(doc_id, "SysHasEmbeddings")

    async def wait_for_indexing(self, timeout: int = 5) -> bool:
        try:
            response = await self._request(
                "GET", "/api/query/waitForFullTextSearchIndexing", params={"timeout": timeout}
            )
        except OpenArchError:
            return False
        return response.json().get("indexing") == "done"

    async def list_embedded_doc_ids(self, scope: str | None = None, *, limit: int = 500) -> list[str]:
        """Ids of documents that hold embeddings — ACL-filtered, optionally within a subtree."""
        query = "SELECT * FROM SysContent WHERE sys_mixinTypes = 'SysHasEmbeddings'"
        if scope:
            safe = re.sub(r"[^A-Za-z0-9-]", "", scope)
            query += f" AND sys_ancestorIds = '{safe}'"
        result = await self.query({"query": query, "limit": limit})
        return [d["sys_id"] for d in result.get("documents", []) if d.get("sys_id")]

    async def list_embedding_child_ids(self, doc_id: str, *, limit: int = 100) -> list[str]:
        """Ids of the SysEmbeddings children under a document."""
        safe = re.sub(r"[^A-Za-z0-9-]", "", doc_id)
        query = f"SELECT * FROM SysEmbeddings WHERE sys_parentId = '{safe}'"
        result = await self.query({"query": query, "limit": limit})
        return [d["sys_id"] for d in result.get("documents", []) if d.get("sys_id")]

    async def semantic_search(
        self,
        vector: list[float],
        *,
        embedding_type: str | None = None,
        scope: str | None = None,
        limit: int = 10,
        chunk_fts: str | None = None,
    ) -> dict[str, Any]:
        """One kNN query over the caller's embedded chunks; OpenArch applies ACLs.

        With ``chunk_fts`` OpenArch runs hybrid search instead: kNN and BM25 over the
        chunk text, merged with reciprocal rank fusion (so scores are rank-based).
        """
        query = "SELECT * FROM SysContent WHERE sys_mixinTypes = 'SysHasEmbeddings'"
        if scope:
            safe = re.sub(r"[^A-Za-z0-9-]", "", scope)
            query += f" AND sys_ancestorIds = '{safe}'"
        payload: dict[str, Any] = {"vector": vector, "query": query, "limit": limit}
        if embedding_type:
            payload["embeddingType"] = embedding_type
        if chunk_fts:
            payload["chunkFTS"] = chunk_fts
        response = await self._request("POST", "/api/query/embeddings", json=payload)
        return {"embeddings": response.json().get("embeddings", [])}

    async def fetch_chunk_texts(self, doc_id: str, *, limit: int = 100) -> list[str]:
        """All stored chunk texts for a document, read back from the embeddings index."""
        return [h.get("sysembed_text") or "" for h in await self.fetch_embeddings(doc_id, limit=limit)]

    async def fetch_embeddings(self, doc_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        """Full SysEmbeddings records for a document from OpenArch's vector index."""
        payload = {
            "vector": [0.0] * 1024,
            "query": f"SELECT * FROM SysContent WHERE sys_id = '{doc_id}'",
            "limit": limit,
        }
        response = await self._request("POST", "/api/query/embeddings", json=payload)
        return response.json().get("embeddings", [])

