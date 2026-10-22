"""Domain vocabulary and invariants."""

from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure
from autoresearch.domain.events import DomainEvent, EventKind, EventPage
from autoresearch.domain.models import (
    AccessPolicy,
    Artifact,
    ArtifactKind,
    ArtifactSubmission,
    Candidate,
    ResearchPlan,
    ResearchRun,
    RunSpec,
    RunStatus,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
)

__all__ = [
    "AccessPolicy",
    "Artifact",
    "ArtifactKind",
    "ArtifactSubmission",
    "AutoResearchError",
    "Candidate",
    "DomainEvent",
    "ErrorCategory",
    "EventKind",
    "EventPage",
    "Failure",
    "ResearchPlan",
    "ResearchRun",
    "RunSpec",
    "RunStatus",
    "SourceDocument",
    "SourceKind",
    "SourceRef",
    "SourceVersion",
]
