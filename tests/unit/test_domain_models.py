from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autoresearch.domain import (
    Artifact,
    ArtifactKind,
    ArtifactSubmission,
    DomainEvent,
    ErrorCategory,
    EventKind,
    Failure,
    ResearchPlan,
    SourceKind,
)


def test_research_plan_requires_include_term() -> None:
    with pytest.raises(ValueError, match="include term"):
        ResearchPlan(question="Agent 自进化", include_terms=())


def test_event_requires_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        DomainEvent(
            id="event-1",
            run_id="run-1",
            sequence=0,
            kind=EventKind.RUN_STARTED,
            occurred_at=datetime(2026, 10, 22),
        )


def test_transient_failure_retries_by_default() -> None:
    failure = Failure(
        category=ErrorCategory.TRANSIENT,
        code="source.rate_limited",
        message="source rate limited",
    )

    assert failure.should_retry is True


def test_artifact_is_immutable_and_versioned() -> None:
    submission = ArtifactSubmission(
        kind=ArtifactKind.OVERVIEW,
        work_id="work-1",
        markdown="# 速览",
        structured={"conclusion": "test"},
        evidence_ids=("evidence-1",),
        warnings=(),
        skill_name="analyze-source",
        skill_version="0.1.0",
    )
    artifact = Artifact(
        id="artifact-1",
        run_id="run-1",
        version=1,
        created_at=datetime.now(UTC),
        submission=submission,
    )

    with pytest.raises(AttributeError):
        artifact.version = 2  # type: ignore[misc]


def test_source_kind_is_limited_to_poc_sources() -> None:
    assert {kind.value for kind in SourceKind} == {"arxiv", "github", "rss", "manual_url"}
