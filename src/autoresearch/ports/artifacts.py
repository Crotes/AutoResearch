"""Validated artifact submission seam."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from autoresearch.domain.models import Artifact, ArtifactSubmission


@runtime_checkable
class ArtifactSubmissionPort(Protocol):
    def submit(self, run_id: str, submission: ArtifactSubmission) -> Artifact: ...
