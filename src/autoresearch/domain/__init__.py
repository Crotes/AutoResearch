"""Domain vocabulary and invariants."""

from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure
from autoresearch.domain.events import DomainEvent, EventKind, EventPage
from autoresearch.domain.library import (
    ArtifactValidity,
    Evidence,
    ResearchProject,
    ReviewDecision,
    ReviewKind,
    ReviewOutcome,
    SkillVersion,
    Work,
)
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
    "ArtifactValidity",
    "AutoResearchError",
    "Candidate",
    "DomainEvent",
    "ErrorCategory",
    "EventKind",
    "EventPage",
    "Evidence",
    "Failure",
    "ResearchPlan",
    "ResearchProject",
    "ResearchRun",
    "ReviewDecision",
    "ReviewKind",
    "ReviewOutcome",
    "RunSpec",
    "RunStatus",
    "SkillVersion",
    "SourceDocument",
    "SourceKind",
    "SourceRef",
    "SourceVersion",
    "Work",
]
