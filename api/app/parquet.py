"""Embedding chunking, vector normalization, and OpenArch-compatible Parquet.

OpenArch stores one `SysEmbeddings` child document per source document, carrying a
Parquet blob whose rows match its embedding schema (see
`modules/platform/openarch-opensearch/src/test/resources/schemas/embedding.avsc`).
OpenArch's EmbeddingModel pads vectors to 1024 and rejects longer ones, so Studio
normalizes to exactly that width before writing — and, critically, uses the same
normalization for query vectors so stored and query dimensions always agree.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass

import pyarrow as pa
import pyarrow.parquet as pq

VECTOR_SIZE = 1024
_CHUNK_NAMESPACE = uuid.UUID("5f6d1b2e-0000-4000-8000-000000000001")

# Arrow schema mirroring embedding.avsc (id, type, vector, text, blobref, location).
EMBEDDING_SCHEMA = pa.schema(
    [
        pa.field("id", pa.string(), nullable=False),
        pa.field("type", pa.string(), nullable=False),
        pa.field("vector", pa.list_(pa.float64()), nullable=False),
        pa.field("text", pa.string(), nullable=False),
        pa.field("blobref", pa.string(), nullable=True),
        pa.field(
            "location",
            pa.struct(
                [
                    pa.field(
                        "text",
                        pa.struct(
                            [pa.field("page", pa.int32()), pa.field("paragraph", pa.int32())]
                        ),
                        nullable=True,
                    )
                ]
            ),
            nullable=True,
        ),
    ]
)


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    page: int
    paragraph: int


@dataclass(frozen=True)
class EmbeddedChunk:
    id: str
    text: str
    vector: list[float]
    page: int
    paragraph: int


def normalize_vector(vector: list[float]) -> list[float]:
    """Pad a vector with zeros to exactly VECTOR_SIZE; reject empty or oversized ones."""
    if not vector:
        raise ValueError("vector must be non-empty")
    if len(vector) > VECTOR_SIZE:
        raise ValueError(f"vector length {len(vector)} exceeds {VECTOR_SIZE}")
    if len(vector) == VECTOR_SIZE:
        return list(vector)
    return list(vector) + [0.0] * (VECTOR_SIZE - len(vector))


def chunk_text(text: str, *, max_chars: int = 1000) -> list[Chunk]:
    """Split text into deterministic, paragraph-based chunks."""
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n")]
    paragraphs = [p for p in paragraphs if p]

    chunks: list[Chunk] = []
    index = 0
    for paragraph in paragraphs:
        pieces = [paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars)]
        for piece in pieces:
            chunk_id = str(uuid.uuid5(_CHUNK_NAMESPACE, f"{index}:{piece}"))
            chunks.append(Chunk(id=chunk_id, text=piece, page=1, paragraph=index + 1))
            index += 1
    return chunks


_HEADING = re.compile(r"#{1,6}\s+\S")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def _wrap(text: str, limit: int) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _wrap_table(block: str, limit: int) -> list[str]:
    """Pack whole table rows into pieces of at most `limit` chars."""
    pieces: list[str] = []
    current = ""
    for row in block.splitlines():
        if len(row) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_wrap(row, limit))
        elif current and len(current) + 1 + len(row) > limit:
            pieces.append(current)
            current = row
        else:
            current = f"{current}\n{row}" if current else row
    if current:
        pieces.append(current)
    return pieces


def chunk_pages(pages: list[str], *, max_chars: int = 1000) -> list[Chunk]:
    """Chunk per-page Markdown into blocks with real page numbers.

    Consecutive paragraphs under one heading on one page are packed into a chunk up
    to `max_chars`; tables are never packed. The latest heading, which carries across
    pages, prefixes the chunks that follow it; oversized blocks are split to fit.
    """
    chunks: list[Chunk] = []
    heading = ""
    for page_number, page in enumerate(pages, start=1):
        paragraph = 0
        pack = ""

        def emit(text: str) -> None:
            nonlocal paragraph
            paragraph += 1
            chunk_id = str(uuid.uuid5(_CHUNK_NAMESPACE, f"{len(chunks)}:{text}"))
            chunks.append(Chunk(id=chunk_id, text=text, page=page_number, paragraph=paragraph))

        def flush_pack() -> None:
            nonlocal pack
            if pack:
                emit(pack)
                pack = ""

        # Blank lines and heading lines both end a block; a heading line starts the next.
        segments: list[tuple[str, str]] = []
        for raw in _BLANK_LINE.split(page.replace("\r\n", "\n")):
            lines: list[str] = []
            for line in raw.splitlines():
                if _HEADING.match(line):
                    segments.append(("body", "\n".join(lines)))
                    segments.append(("heading", line.strip()))
                    lines = []
                else:
                    lines.append(line)
            segments.append(("body", "\n".join(lines)))
        for kind, content in segments:
            if kind == "heading":
                flush_pack()
                heading = content
                continue
            block = content.strip()
            if not block:
                continue
            prefix = f"{heading}\n" if heading and len(heading) + 1 < max_chars else ""
            limit = max_chars - len(prefix)
            if all(line.startswith("|") for line in block.splitlines()):
                flush_pack()
                for piece in _wrap_table(block, limit):
                    emit(prefix + piece)
            elif len(block) > limit:
                flush_pack()
                for piece in _wrap(block, limit):
                    emit(prefix + piece)
            elif pack and len(pack) + 2 + len(block) <= max_chars:
                pack = f"{pack}\n\n{block}"
            else:
                flush_pack()
                pack = prefix + block
        flush_pack()
    return chunks


def write_embeddings(chunks: list[EmbeddedChunk], embedding_type: str) -> bytes:
    """Serialize embedded chunks to an OpenArch-compatible Parquet blob."""
    if not chunks:
        raise ValueError("no chunks to write")

    lengths = {len(c.vector) for c in chunks}
    if lengths != {VECTOR_SIZE}:
        raise ValueError(f"all vectors must be normalized to {VECTOR_SIZE}; saw {sorted(lengths)}")

    table = pa.table(
        {
            "id": [c.id for c in chunks],
            "type": [embedding_type] * len(chunks),
            "vector": [c.vector for c in chunks],
            "text": [c.text for c in chunks],
            "blobref": [None] * len(chunks),
            "location": [{"text": {"page": c.page, "paragraph": c.paragraph}} for c in chunks],
        },
        schema=EMBEDDING_SCHEMA,
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()
