"""Core immutable domain records shared across modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    REVIEW_REQUIRED = "review_required"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceKind(StrEnum):
    ARXIV = "arxiv"
    GITHUB = "github"
    RSS = "rss"
    MANUAL_URL = "manual_url"


class AccessPolicy(StrEnum):
    PERSIST = "persist"
    CONTROLLED = "controlled"
    METADATA_ONLY = "metadata_only"


class ArtifactKind(StrEnum):
    OVERVIEW = "overview"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    question: str
    include_terms: tuple[str, ...]
    exclude_terms: tuple[str, ...] = ()
    languages: tuple[str, ...] = ("zh", "en")
    source_kinds: tuple[SourceKind, ...] = ()
    start_date: str | None = None
    end_date: str | None = None
    seed_urls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("research question must not be empty")
        if not self.include_terms:
            raise ValueError("research plan requires at least one include term")


@dataclass(frozen=True, slots=True)
class RunSpec:
    project_id: str
    plan: ResearchPlan
    workflow_version: str
    skill_versions: dict[str, str]
    max_duration_seconds: int
    max_candidates: int

    def __post_init__(self) -> None:
        if self.max_duration_seconds <= 0:
            raise ValueError("run duration budget must be positive")
        if self.max_candidates <= 0:
            raise ValueError("candidate budget must be positive")


@dataclass(frozen=True, slots=True)
class ResearchRun:
    id: str
    project_id: str
    status: RunStatus
    plan: ResearchPlan
    workflow_version: str
    created_at: datetime
    updated_at: datetime
    checkpoint: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("run timestamps must include a timezone")
        if self.updated_at < self.created_at:
            raise ValueError("run update time cannot precede creation time")


@dataclass(frozen=True, slots=True)
class SourceRef:
    kind: SourceKind
    locator: str

    def __post_init__(self) -> None:
        if not self.locator.strip():
            raise ValueError("source locator must not be empty")


@dataclass(frozen=True, slots=True)
class Candidate:
    source_ref: SourceRef
    title: str
    canonical_url: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceVersion:
    id: str
    work_id: str
    source_ref: SourceRef
    canonical_url: str
    retrieved_at: datetime
    content_hash: str
    access_policy: AccessPolicy
    license: str | None = None

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("source retrieval time must include a timezone")
        if not self.content_hash:
            raise ValueError("source version requires a content hash")


@dataclass(frozen=True, slots=True)
class SourceDocument:
    source_version: SourceVersion
    media_type: str
    text: str
    chunks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactSubmission:
    kind: ArtifactKind
    work_id: str | None
    markdown: str
    structured: dict[str, Any]
    evidence_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    skill_name: str
    skill_version: str


@dataclass(frozen=True, slots=True)
class Artifact:
    id: str
    run_id: str
    version: int
    created_at: datetime
    submission: ArtifactSubmission

    def __post_init__(self) -> None:
        if self.version <= 0:
            raise ValueError("artifact version must be positive")
        if self.created_at.tzinfo is None:
            raise ValueError("artifact timestamp must include a timezone")
