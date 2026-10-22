"""Shared block model, normalization, and structure-aware chunking.

Chunk anchors are positional and deterministic: the same blocks always produce
the same chunk indexes, which is what makes ``<source_version_id>#chunk-<N>``
a stable evidence anchor. PDF chunks additionally carry their page number.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

DEFAULT_TARGET_CHARS = 1500

_WHITESPACE = re.compile(r"[ \t\r\f\v]+")


@dataclass(frozen=True, slots=True)
class Block:
    text: str
    kind: str = "paragraph"  # "heading" | "paragraph" | "page"
    page: int | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int  # 1-based, stable for identical input
    text: str
    page: int | None = None


def normalize_text(text: str) -> str:
    """NFC-normalize and collapse inline whitespace, preserving line breaks."""
    normalized = unicodedata.normalize("NFC", text)
    lines = (_WHITESPACE.sub(" ", line).strip() for line in normalized.split("\n"))
    return "\n".join(line for line in lines if line)


def chunk_anchor(source_version_id: str, index: int, page: int | None = None) -> str:
    anchor = f"{source_version_id}#chunk-{index}"
    if page is not None:
        anchor += f"@page-{page}"
    return anchor


def chunk_blocks(
    blocks: list[Block], *, target_chars: int = DEFAULT_TARGET_CHARS
) -> tuple[Chunk, ...]:
    """Greedy structure-aware chunking.

    Headings always start a new chunk; pages never merge; blocks are otherwise
    packed until ``target_chars``. Oversized single blocks are hard-split at
    whitespace so every chunk stays near the target.
    """
    chunks: list[Chunk] = []
    current: list[str] = []
    current_len = 0
    current_page: int | None = None

    def flush() -> None:
        nonlocal current, current_len, current_page
        if current:
            chunks.append(
                Chunk(index=len(chunks) + 1, text="\n\n".join(current), page=current_page)
            )
        current = []
        current_len = 0
        current_page = None

    def emit_text(text: str, page: int | None) -> None:
        nonlocal current_len, current_page
        if not current:
            current_page = page
        current.append(text)
        current_len += len(text)

    for block in blocks:
        if not block.text:
            continue
        if block.kind == "heading" or (block.page != current_page and current):
            flush()
        if len(block.text) > target_chars:
            flush()
            for piece in _hard_split(block.text, target_chars):
                emit_text(piece, block.page)
                flush()
            continue
        if current and current_len + len(block.text) > target_chars:
            flush()
        emit_text(block.text, block.page)
    flush()
    return tuple(chunks)


def _hard_split(text: str, target: int) -> list[str]:
    pieces: list[str] = []
    remaining = text
    while len(remaining) > target:
        cut = remaining.rfind(" ", 0, target)
        if cut <= 0:
            cut = target
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces
