"""Composite SourceAcquisition: dispatch by SourceKind with failure isolation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure
from autoresearch.domain.models import (
    Candidate,
    ResearchPlan,
    SourceDocument,
    SourceKind,
    SourceRef,
)
from autoresearch.ports.sources import SourceAcquisition


class CompositeSourceAdapter:
    """Fan discovery out per kind; one failing source never sinks the others."""

    def __init__(self, sources: Mapping[SourceKind, SourceAcquisition]) -> None:
        self._sources = dict(sources)

    def discover(self, plan: ResearchPlan) -> Iterable[Candidate]:
        candidates, _failures = self.discover_with_failures(plan)
        return candidates

    def discover_with_failures(
        self, plan: ResearchPlan
    ) -> tuple[tuple[Candidate, ...], tuple[Failure, ...]]:
        kinds = plan.source_kinds or tuple(self._sources)
        candidates: list[Candidate] = []
        failures: list[Failure] = []
        for kind in kinds:
            source = self._sources.get(kind)
            if source is None:
                failures.append(
                    Failure(
                        category=ErrorCategory.PERMANENT,
                        code="sources.kind_not_configured",
                        message=f"no source adapter configured for kind {kind!r}",
                        details={"source_kind": str(kind)},
                    )
                )
                continue
            try:
                candidates.extend(source.discover(plan))
            except AutoResearchError as error:
                failures.append(self._annotate(error.failure, kind))
            except Exception as error:
                failures.append(
                    Failure(
                        category=ErrorCategory.INTERNAL,
                        code="sources.unexpected_error",
                        message=f"source {kind!r} failed unexpectedly: {error}",
                        details={"source_kind": str(kind)},
                    )
                )
        return tuple(candidates), tuple(failures)

    def materialize(self, source_ref: SourceRef) -> SourceDocument:
        source = self._sources.get(source_ref.kind)
        if source is None:
            raise AutoResearchError(
                Failure(
                    category=ErrorCategory.PERMANENT,
                    code="sources.kind_not_configured",
                    message=f"no source adapter configured for kind {source_ref.kind!r}",
                )
            )
        return source.materialize(source_ref)

    @staticmethod
    def _annotate(failure: Failure, kind: SourceKind) -> Failure:
        return Failure(
            category=failure.category,
            code=failure.code,
            message=failure.message,
            retryable=failure.retryable,
            details={**failure.details, "source_kind": str(kind)},
        )
