"""In-memory PoC implementation of the library seam.

Backed by the documents materialized during a run plus a fixed entry list, so
the MCP tools can be exercised without any external service.
"""

from __future__ import annotations

from collections.abc import Iterable

from autoresearch.domain.models import SourceDocument
from autoresearch.ports.library import LibraryChunk, LibraryEntry


class InMemoryLibrarySearch:
    def __init__(
        self,
        entries: Iterable[LibraryEntry] = (),
        documents: dict[str, SourceDocument] | None = None,
    ) -> None:
        self._entries = tuple(entries)
        self._documents = dict(documents or {})

    def register_document(self, document: SourceDocument) -> None:
        self._documents[document.source_version.id] = document

    def search(self, query: str, *, limit: int = 10) -> tuple[LibraryEntry, ...]:
        needle = query.strip().lower()
        if not needle:
            return ()
        matches = [
            entry
            for entry in self._entries
            if needle in entry.title.lower() or needle in entry.summary.lower()
        ]
        return tuple(matches[: max(limit, 0)])

    def read_chunks(
        self, source_version_id: str, *, start: int = 0, limit: int = 5
    ) -> tuple[LibraryChunk, ...]:
        try:
            document = self._documents[source_version_id]
        except KeyError as error:
            raise KeyError(f"unknown source version: {source_version_id}") from error
        selected = document.chunks[max(start, 0) : max(start, 0) + max(limit, 0)]
        return tuple(
            LibraryChunk(
                source_version_id=source_version_id, index=max(start, 0) + offset, text=text
            )
            for offset, text in enumerate(selected)
        )
