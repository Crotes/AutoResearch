from __future__ import annotations

from autoresearch.application.content.chunk import (
    Block,
    chunk_anchor,
    chunk_blocks,
    normalize_text,
)


def paragraph(text: str, page: int | None = None) -> Block:
    return Block(text=text, page=page)


def test_chunking_is_deterministic_and_anchors_stable() -> None:
    blocks = [paragraph("aaaaaaaaaaaa"), paragraph("bbbbbbbbbbbb"), paragraph("cccccccccccc")]
    first = chunk_blocks(blocks, target_chars=20)
    second = chunk_blocks(blocks, target_chars=20)
    assert first == second
    assert [chunk.index for chunk in first] == [1, 2, 3]
    assert [chunk_anchor("sv-1", chunk.index) for chunk in first] == [
        "sv-1#chunk-1",
        "sv-1#chunk-2",
        "sv-1#chunk-3",
    ]


def test_inserted_paragraph_shifts_following_anchors_predictably() -> None:
    base = [paragraph("aaaaaaaaaaaa"), paragraph("bbbbbbbbbbbb"), paragraph("cccccccccccc")]
    inserted = [paragraph("aaaaaaaaaaaa"), paragraph("xxxxxxxxxxxx"), *base[1:]]
    base_chunks = chunk_blocks(base, target_chars=20)
    shifted_chunks = chunk_blocks(inserted, target_chars=20)
    assert [chunk.text for chunk in base_chunks] == [
        "aaaaaaaaaaaa",
        "bbbbbbbbbbbb",
        "cccccccccccc",
    ]
    assert [chunk.text for chunk in shifted_chunks] == [
        "aaaaaaaaaaaa",
        "xxxxxxxxxxxx",
        "bbbbbbbbbbbb",
        "cccccccccccc",
    ]


def test_headings_start_new_chunks() -> None:
    blocks = [
        paragraph("intro text"),
        Block(text="Methods", kind="heading"),
        paragraph("method body"),
    ]
    chunks = chunk_blocks(blocks, target_chars=1000)
    assert [chunk.text for chunk in chunks] == ["intro text", "Methods\n\nmethod body"]


def test_pages_never_merge() -> None:
    blocks = [paragraph("page one", page=1), paragraph("page two", page=2)]
    chunks = chunk_blocks(blocks, target_chars=1000)
    assert [chunk.page for chunk in chunks] == [1, 2]


def test_oversized_block_is_hard_split() -> None:
    blocks = [paragraph(" ".join(["word"] * 100))]
    chunks = chunk_blocks(blocks, target_chars=100)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 110 for chunk in chunks)
    assert " ".join(chunk.text for chunk in chunks).count("word") == 100


def test_pdf_anchor_carries_page() -> None:
    assert chunk_anchor("sv-9", 2, 3) == "sv-9#chunk-2@page-3"
    assert chunk_anchor("sv-9", 2) == "sv-9#chunk-2"


def test_normalize_text_collapses_whitespace_and_nfc() -> None:
    assert normalize_text("a  b\tc\n\n d ") == "a b c\nd"
    assert normalize_text("café") == "café"
