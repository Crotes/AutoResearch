"""Read-only access to the curated research library."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from autoresearch.domain.library import ReviewDecision
from autoresearch.domain.models import ArtifactKind, SourceDocument


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    """Summary of a stored research artifact; never carries full text."""

    artifact_id: str
    run_id: str
    kind: ArtifactKind
    title: str
    summary: str
    work_id: str | None = None
    validity: str = "valid"


@dataclass(frozen=True, slots=True)
class LibraryChunk:
    """A source chunk whose public anchor index starts at 1."""

    source_version_id: str
    index: int
    text: str


@runtime_checkable
class LibraryMaintenance(Protocol):
    """Write-side operations owned by the persistent library adapter."""

    def save_source(self, document: SourceDocument) -> str: ...

    def delete_source(self, source_version_id: str) -> tuple[str, ...]: ...

    def add_review(self, decision: ReviewDecision) -> ReviewDecision: ...


@runtime_checkable
class LibrarySearch(Protocol):
    """Query stored artifacts and read back chunks of materialized sources."""

    def search(self, query: str, *, limit: int = 10) -> tuple[LibraryEntry, ...]: ...

    def read_chunks(
        self, source_version_id: str, *, start: int = 0, limit: int = 5
    ) -> tuple[LibraryChunk, ...]: ...
