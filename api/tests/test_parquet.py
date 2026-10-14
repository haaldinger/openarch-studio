"""Vector normalization, chunking, and Parquet shape against OpenArch's schema."""

from __future__ import annotations

import io

import pyarrow.parquet as pq
import pytest

from app.parquet import (
    VECTOR_SIZE,
    EmbeddedChunk,
    chunk_text,
    normalize_vector,
    write_embeddings,
)


def test_short_vector_is_zero_padded() -> None:
    out = normalize_vector([0.1, 0.2, 0.3])
    assert len(out) == VECTOR_SIZE
    assert out[:3] == [0.1, 0.2, 0.3]
    assert out[3] == 0.0 and out[-1] == 0.0


def test_exact_length_vector_is_unchanged() -> None:
    vector = [0.5] * VECTOR_SIZE
    assert normalize_vector(vector) == vector


def test_embedding_dimension_invalid_before_write() -> None:
    with pytest.raises(ValueError):
        normalize_vector([])
    with pytest.raises(ValueError):
        normalize_vector([0.0] * (VECTOR_SIZE + 1))


def test_chunk_ids_are_deterministic_uuids() -> None:
    text = "First paragraph.\n\nSecond paragraph."
    a = chunk_text(text)
    b = chunk_text(text)
    assert [c.id for c in a] == [c.id for c in b]
    assert len(a) == 2
    # Each id must be a valid UUID (OpenArch rejects non-UUID embedding ids).
    import uuid

    for chunk in a:
        uuid.UUID(chunk.id)


def test_long_paragraph_is_split_by_max_chars() -> None:
    chunks = chunk_text("x" * 2500, max_chars=1000)
    assert len(chunks) == 3
    assert "".join(c.text for c in chunks) == "x" * 2500


def test_write_embeddings_matches_openarch_columns() -> None:
    chunks = [
        EmbeddedChunk(
            id="00000000-0000-4000-8000-000000000001",
            text="hello",
            vector=normalize_vector([0.1, 0.2]),
            page=1,
            paragraph=1,
        )
    ]
    blob = write_embeddings(chunks, "nomic-embed-text")
    table = pq.read_table(io.BytesIO(blob))

    assert table.column_names == ["id", "type", "vector", "text", "blobref", "location"]
    row = table.to_pylist()[0]
    assert row["type"] == "nomic-embed-text"
    assert len(row["vector"]) == VECTOR_SIZE
    assert row["text"] == "hello"
    assert row["blobref"] is None
    assert row["location"]["text"] == {"page": 1, "paragraph": 1}


def test_write_rejects_unnormalized_vectors() -> None:
    chunks = [EmbeddedChunk(id="x", text="t", vector=[0.1, 0.2], page=1, paragraph=1)]
    with pytest.raises(ValueError):
        write_embeddings(chunks, "model")


def test_write_rejects_empty_chunk_list() -> None:
    with pytest.raises(ValueError):
        write_embeddings([], "model")
