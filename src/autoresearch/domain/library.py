"""Persistent research-library vocabulary.

These records deliberately contain no SQLite types.  The storage adapter maps
them to rows and keeps the application boundary usable with another database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReviewKind(StrEnum):
    PLAN = "plan"
    SOURCE = "source"
    ARTIFACT = "artifact"
    FINAL = "final"


class ReviewOutcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ArtifactValidity(StrEnum):
    VALID = "valid"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class ResearchProject:
    id: str
    name: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class Work:
    id: str
    title: str
    identity_keys: tuple[str, ...] = ()
    metadata: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    artifact_id: str
    source_version_id: str
    chunk_index: int
    quote: str = ""


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    id: str
    run_id: str
    kind: ReviewKind
    outcome: ReviewOutcome
    reviewer: str
    comment: str
    created_at: datetime
    artifact_id: str | None = None
    supersedes_id: str | None = None
    work_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillVersion:
    name: str
    version: str
    manifest_hash: str = ""
    source_ref: str = ""
