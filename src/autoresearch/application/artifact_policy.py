"""Workflow-aware policy enforcement for artifact submissions.

The MCP tools expose the library's submission port directly.  Wrapping it here
turns the human review gates from conventions into hard constraints: analyses
may only target the latest approved source selection, syntheses may only cite
evidence produced for selected works, and overviews are only accepted while
the run is still collecting candidates.
"""

from __future__ import annotations

from typing import Protocol

from autoresearch.domain.library import ReviewDecision, ReviewKind, ReviewOutcome
from autoresearch.domain.models import (
    Artifact,
    ArtifactKind,
    ArtifactSubmission,
    ResearchRun,
    RunStatus,
)


class PolicyViolationError(ValueError):
    """A submission violated a workflow policy constraint."""


class ArtifactPolicyLibrary(Protocol):
    """Narrow read/write surface the policy enforcer needs from a library."""

    def get_run(self, run_id: str) -> ResearchRun: ...

    def list_reviews(self, run_id: str) -> tuple[ReviewDecision, ...]: ...

    def list_artifacts(
        self,
        run_id: str,
        *,
        kind: ArtifactKind | None = None,
        include_stale: bool = False,
    ) -> tuple[Artifact, ...]: ...

    def submit(self, run_id: str, submission: ArtifactSubmission) -> Artifact: ...

    def submit_idempotent(
        self, run_id: str, idempotency_key: str, submission: ArtifactSubmission
    ) -> tuple[Artifact, bool]: ...


class PolicyEnforcingArtifacts:
    """Enforce workflow constraints before delegating to the underlying library."""

    def __init__(self, library: ArtifactPolicyLibrary) -> None:
        self._library = library

    def submit(self, run_id: str, submission: ArtifactSubmission) -> Artifact:
        self._enforce(run_id, submission)
        return self._library.submit(run_id, submission)

    def submit_idempotent(
        self, run_id: str, idempotency_key: str, submission: ArtifactSubmission
    ) -> tuple[Artifact, bool]:
        self._enforce(run_id, submission)
        return self._library.submit_idempotent(run_id, idempotency_key, submission)

    def _enforce(self, run_id: str, submission: ArtifactSubmission) -> None:
        if submission.kind is ArtifactKind.OVERVIEW:
            self._enforce_overview(run_id)
        elif submission.kind is ArtifactKind.ANALYSIS:
            self._enforce_analysis(run_id, submission)
        elif submission.kind is ArtifactKind.SYNTHESIS:
            self._enforce_synthesis(run_id, submission)

    def _selected_work_ids(self, run_id: str) -> tuple[str, ...]:
        for review in reversed(self._library.list_reviews(run_id)):
            if review.kind is ReviewKind.SOURCE and review.outcome is ReviewOutcome.APPROVED:
                return review.work_ids
        return ()

    def _enforce_overview(self, run_id: str) -> None:
        run = self._library.get_run(run_id)
        if run.status is not RunStatus.RUNNING or run.checkpoint is not None:
            raise PolicyViolationError(
                "overview submissions are only allowed during initial collection "
                "(run must be RUNNING with no checkpoint)"
            )

    def _enforce_analysis(self, run_id: str, submission: ArtifactSubmission) -> None:
        selected = set(self._selected_work_ids(run_id))
        if not selected:
            raise PolicyViolationError(
                "an approved source selection is required before submitting analyses"
            )
        if submission.work_id is None or submission.work_id not in selected:
            raise PolicyViolationError(
                f"analysis work_id {submission.work_id!r} is not in the approved "
                f"selection {sorted(selected)}"
            )

    def _enforce_synthesis(self, run_id: str, submission: ArtifactSubmission) -> None:
        selected = self._selected_work_ids(run_id)
        if not selected:
            raise PolicyViolationError(
                "an approved source selection is required before submitting synthesis"
            )
        artifacts = self._library.list_artifacts(run_id)
        analyses = {
            artifact.submission.work_id
            for artifact in artifacts
            if artifact.submission.kind is ArtifactKind.ANALYSIS
            and artifact.submission.work_id is not None
        }
        missing = set(selected) - analyses
        if missing:
            raise PolicyViolationError(
                "synthesis requires a valid analysis for every selected work; "
                f"missing analyses: {sorted(missing)}"
            )
        allowed_evidence: set[str] = set()
        for artifact in artifacts:
            if (
                artifact.submission.kind in (ArtifactKind.OVERVIEW, ArtifactKind.ANALYSIS)
                and artifact.submission.work_id in selected
            ):
                allowed_evidence.update(artifact.submission.evidence_ids)
        outside = set(submission.evidence_ids) - allowed_evidence
        if outside:
            raise PolicyViolationError(
                "synthesis evidence references anchors outside the selected works: "
                f"{sorted(outside)}"
            )
