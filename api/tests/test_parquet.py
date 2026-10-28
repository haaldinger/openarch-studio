"""Vector normalization, chunking, and Parquet shape against OpenArch's schema."""

from __future__ import annotations

import io

import pyarrow.parquet as pq
import pytest

from app.parquet import (
    VECTOR_SIZE,
    EmbeddedChunk,
    chunk_pages,
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


def test_chunk_pages_carries_page_numbers() -> None:
    chunks = chunk_pages(["Alpha.", "Beta."])
    assert [(c.page, c.paragraph) for c in chunks] == [(1, 1), (2, 1)]


def test_heading_prefixes_following_chunks_across_pages() -> None:
    chunks = chunk_pages(["## Totals\n\nNet 10", "Gross 12"])
    assert chunks[0].text == "## Totals\nNet 10"
    assert chunks[1].text == "## Totals\nGross 12"


def test_table_kept_whole_when_it_fits() -> None:
    table = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    assert any(c.text.endswith(table) for c in chunk_pages([f"Intro\n\n{table}"]))


def test_oversized_table_splits_on_row_boundaries() -> None:
    rows = "\n".join(f"| {i} | {'x' * 40} |" for i in range(60))
    table = "| n | v |\n|---|---|\n" + rows
    chunks = chunk_pages([table], max_chars=500)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= 500
        assert all(line.startswith("|") for line in c.text.splitlines())


def test_long_paragraph_hard_wraps() -> None:
    chunks = chunk_pages(["x" * 2500])
    assert len(chunks) == 3
    assert all(len(c.text) <= 1000 for c in chunks)


def test_blank_pages_produce_no_chunks() -> None:
    assert chunk_pages(["", "   "]) == []


def test_chunk_pages_ids_are_unique_and_deterministic() -> None:
    pages = ["Same.\n\n| a |\n\nSame.", "Same."]
    first = chunk_pages(pages)
    assert [c.id for c in first] == [c.id for c in chunk_pages(pages)]
    assert len({c.id for c in first}) == 4


def test_prefixed_long_paragraph_stays_within_max_chars() -> None:
    chunks = chunk_pages(["## Heading\n\n" + "y" * 2500], max_chars=500)
    assert all(len(c.text) <= 500 and c.text.startswith("## Heading\n") for c in chunks)


def test_heading_line_without_blank_line_is_a_boundary() -> None:
    chunks = chunk_pages(["intro\n## Heading\nbody"])
    assert [c.text for c in chunks] == ["intro", "## Heading\nbody"]


@pytest.mark.parametrize("sep", [" ", "\t"])
def test_whitespace_only_lines_separate_blocks(sep: str) -> None:
    assert [c.text for c in chunk_pages([f"a\n{sep}\nb"])] == ["a\n\nb"]


def test_short_blocks_pack_into_one_chunk() -> None:
    page = "\n\n".join(f"Line {i}" for i in range(30))
    chunks = chunk_pages([page])
    assert len(chunks) == 1
    assert "Line 0" in chunks[0].text and "Line 29" in chunks[0].text


def test_packing_respects_max_chars() -> None:
    blocks = [f"{i:02d}" + "x" * 38 for i in range(50)]
    chunks = chunk_pages(["\n\n".join(blocks)], max_chars=500)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    packed = [part for c in chunks for part in c.text.split("\n\n")]
    assert packed == blocks


def test_table_is_not_packed_with_paragraphs() -> None:
    chunks = chunk_pages(["Intro\n\n| a |\n|---|\n| 1 |\n\nOutro"])
    assert [c.text for c in chunks] == ["Intro", "| a |\n|---|\n| 1 |", "Outro"]


def test_heading_flushes_pack() -> None:
    chunks = chunk_pages(["a\n\nb\n\n## H\n\nc\n\nd"])
    assert [c.text for c in chunks] == ["a\n\nb", "## H\nc\n\nd"]


def test_page_break_flushes_pack() -> None:
    chunks = chunk_pages(["a\n\nb", "c"])
    assert [(c.text, c.page, c.paragraph) for c in chunks] == [("a\n\nb", 1, 1), ("c", 2, 1)]


def test_only_atx_headings_are_headings() -> None:
    chunks = chunk_pages(["#1 priority\n#hashtag\n\n####### seven"])
    assert [c.text for c in chunks] == ["#1 priority\n#hashtag\n\n####### seven"]
