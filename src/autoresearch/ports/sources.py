"""Source discovery and materialization seam."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from autoresearch.domain.models import Candidate, ResearchPlan, SourceDocument, SourceRef


@runtime_checkable
class SourceAcquisition(Protocol):
    def discover(self, plan: ResearchPlan) -> Iterable[Candidate]: ...

    def materialize(self, source_ref: SourceRef) -> SourceDocument: ...
