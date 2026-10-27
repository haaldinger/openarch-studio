"""Text extraction: Docling (layout-aware markdown) with Tika as fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

PAGE_BREAK = "<!-- studio:page-break -->"


@dataclass
class Extracted:
    markdown: str
    pages: list[str]
    engine: str


class ExtractionFailed(Exception):
    """The extractor could not produce usable text."""


class Extractor(Protocol):
    async def extract(self, content: bytes, mime: str, filename: str) -> Extracted: ...


class DoclingExtractor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def extract(self, content: bytes, mime: str, filename: str) -> Extracted:
        timeout = self._settings.docling_timeout_seconds
        form = {
            "to_formats": "md",
            "do_ocr": "true",
            "md_page_break_placeholder": PAGE_BREAK,
            "image_export_mode": "placeholder",
            "document_timeout": str(timeout),
        }
        url = f"{self._settings.docling_url}/v1/convert/file"
        try:
            # Client timeout outlasts document_timeout so Docling reports its own failure.
            async with httpx.AsyncClient(timeout=timeout + 30.0) as client:
                response = await client.post(
                    url, data=form, files={"files": (filename, content, mime)}
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExtractionFailed(f"docling request failed: {exc!r}") from exc

        status = body.get("status")
        if status in {"failure", "skipped"}:
            raise ExtractionFailed(f"docling status {status}: {body.get('errors')}")
        md = (body.get("document") or {}).get("md_content") or ""
        if not md.strip():
            raise ExtractionFailed("docling returned no text")
        pages = [p.strip() for p in md.split(PAGE_BREAK)]
        return Extracted(markdown="\n\n".join(pages), pages=pages, engine="docling")


class TikaExtractor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def extract(self, content: bytes, mime: str, filename: str) -> Extracted:
        url = f"{self._settings.tika_url}/tika"
        # OCR of large scanned images is slow; allow generous time.
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.put(
                url, content=content, headers={"Accept": "text/plain", "Content-Type": mime}
            )
            response.raise_for_status()
            text = response.text
        return Extracted(markdown=text, pages=[text], engine="tika")


class FallbackExtractor:
    def __init__(self, primary: Extractor, fallback: Extractor) -> None:
        self._primary = primary
        self._fallback = fallback

    async def extract(self, content: bytes, mime: str, filename: str) -> Extracted:
        try:
            return await self._primary.extract(content, mime, filename)
        except ExtractionFailed as exc:
            log.warning("primary extractor failed for %s, falling back: %s", filename, exc)
            return await self._fallback.extract(content, mime, filename)


def build_extractor(settings: Settings) -> FallbackExtractor | TikaExtractor:
    if settings.extractor == "tika":
        return TikaExtractor(settings)
    return FallbackExtractor(DoclingExtractor(settings), TikaExtractor(settings))
