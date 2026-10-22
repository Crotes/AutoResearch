"""Content processing pipeline: bytes + version metadata -> SourceDocument.

The access-policy gate is structural: for ``metadata_only``/``controlled``
versions the returned document carries no body text at all, so content that
may not be persisted never reaches storage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from autoresearch.application.content.chunk import (
    Block,
    Chunk,
    chunk_anchor,
    chunk_blocks,
    normalize_text,
)
from autoresearch.application.content.detect import ContentFormat, detect_format
from autoresearch.application.content.html import extract_html_blocks
from autoresearch.application.content.pdf import extract_pdf_pages
from autoresearch.domain.models import AccessPolicy, SourceDocument, SourceVersion

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True, slots=True)
class ChunkRef:
    index: int
    anchor: str
    page: int | None


class ContentProcessor:
    def __init__(self, *, target_chars: int = 1500) -> None:
        self._target_chars = target_chars

    def process(
        self, source_version: SourceVersion, raw: bytes, media_type: str | None = None
    ) -> SourceDocument:
        document, _refs = self.process_with_refs(source_version, raw, media_type)
        return document

    def process_with_refs(
        self, source_version: SourceVersion, raw: bytes, media_type: str | None = None
    ) -> tuple[SourceDocument, tuple[ChunkRef, ...]]:
        if source_version.access_policy in (AccessPolicy.METADATA_ONLY, AccessPolicy.CONTROLLED):
            document = SourceDocument(
                source_version=source_version, media_type=media_type or "", text="", chunks=()
            )
            return document, ()
        content_format = detect_format(raw, media_type)
        blocks = self._blocks(content_format, raw)
        chunks = chunk_blocks(blocks, target_chars=self._target_chars)
        refs = tuple(self._ref(source_version, chunk, content_format) for chunk in chunks)
        document = SourceDocument(
            source_version=source_version,
            media_type=media_type or str(content_format),
            text="\n\n".join(chunk.text for chunk in chunks),
            chunks=tuple(chunk.text for chunk in chunks),
        )
        return document, refs

    def _blocks(self, content_format: ContentFormat, raw: bytes) -> list[Block]:
        if content_format is ContentFormat.PDF:
            return [
                Block(text=normalize_text(page.text), kind="page", page=page.page)
                for page in extract_pdf_pages(raw)
            ]
        text = raw.decode("utf-8", errors="replace")
        if content_format is ContentFormat.HTML:
            return extract_html_blocks(text)
        if content_format is ContentFormat.MARKDOWN:
            return _markdown_blocks(text)
        return [
            Block(text=normalize_text(part)) for part in re.split(r"\n\s*\n", text) if part.strip()
        ]

    @staticmethod
    def _ref(
        source_version: SourceVersion, chunk: Chunk, content_format: ContentFormat
    ) -> ChunkRef:
        page = chunk.page if content_format is ContentFormat.PDF else None
        return ChunkRef(
            index=chunk.index,
            anchor=chunk_anchor(source_version.id, chunk.index, page),
            page=page,
        )


def _markdown_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    for part in re.split(r"\n\s*\n", text):
        stripped = part.strip()
        if not stripped:
            continue
        match = _HEADING.match(stripped)
        if match:
            blocks.append(Block(text=normalize_text(match.group(2)), kind="heading"))
        else:
            blocks.append(Block(text=normalize_text(part)))
    return blocks
