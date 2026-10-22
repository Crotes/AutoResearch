from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autoresearch.adapters.sqlite import IdempotencyConflict, SqliteResearchLibrary
from autoresearch.domain.library import (
    ResearchProject,
    ReviewDecision,
    ReviewKind,
    ReviewOutcome,
    Work,
)
from autoresearch.domain.models import (
    AccessPolicy,
    ArtifactKind,
    ArtifactSubmission,
    ResearchPlan,
    ResearchRun,
    RunStatus,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def source(
    source_id: str = "source-1", *, policy: AccessPolicy = AccessPolicy.PERSIST
) -> SourceDocument:
    return SourceDocument(
        source_version=SourceVersion(
            id=source_id,
            work_id="work-1",
            source_ref=SourceRef(SourceKind.ARXIV, "arxiv:1"),
            canonical_url="https://arxiv.org/abs/1",
            retrieved_at=NOW,
            content_hash="a" * 64,
            access_policy=policy,
        ),
        media_type="text/plain",
        text="first paragraph\nsecond paragraph",
        chunks=("first paragraph", "second paragraph"),
    )


def run() -> ResearchRun:
    plan = ResearchPlan(question="q", include_terms=("agent",))
    return ResearchRun(
        id="run-1",
        project_id="project-1",
        status=RunStatus.RUNNING,
        plan=plan,
        workflow_version="w1",
        created_at=NOW,
        updated_at=NOW,
    )


def artifact(
    *,
    kind: ArtifactKind = ArtifactKind.OVERVIEW,
    evidence: str = "source-1#chunk-1",
    dependency: tuple[str, ...] = (),
) -> ArtifactSubmission:
    return ArtifactSubmission(
        kind=kind,
        work_id="work-1",
        markdown="A useful result",
        structured={"title": "Self refining agents", "summary": "useful result"},
        evidence_ids=(evidence,),
        warnings=(),
        skill_name="collect-sources",
        skill_version="1.0.0",
        dependency_artifact_ids=dependency,
    )


def prepared(tmp_path):
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    library.save_project(ResearchProject("project-1", "Lab"))
    library.save_run(run())
    library.save_work(Work("work-1", "Self refining agents", ("doi:10.1/abc",)))
    library.save_source(source())
    return library


def test_persists_reopens_and_deduplicates_work_identity(tmp_path) -> None:
    library = prepared(tmp_path)
    assert library.resolve_work("doi:10.1/abc") == "work-1"
    assert library.save_source(source("source-duplicate")) == "source-1"
    library.close()
    reopened = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    assert reopened.read_chunks("source-1", start=1, limit=2)[1].index == 2
    assert reopened.search("self refining") == ()


def test_submit_is_transactional_and_idempotent(tmp_path) -> None:
    library = prepared(tmp_path)
    first, replay = library.submit_idempotent("run-1", "request-1", artifact())
    assert replay is False
    again, replay = library.submit_idempotent("run-1", "request-1", artifact())
    assert replay is True and again.id == first.id
    with pytest.raises(IdempotencyConflict):
        library.submit_idempotent("run-1", "request-1", artifact(kind=ArtifactKind.ANALYSIS))
    assert len(library.search("refining")) == 1
    with pytest.raises(ValueError):
        library.submit("run-1", artifact(evidence="source-1#chunk-9"))
    assert library.search("useful")


def test_review_is_append_only_and_source_deletion_stales_dependents(tmp_path) -> None:
    library = prepared(tmp_path)
    first = library.submit("run-1", artifact())
    derived = library.submit("run-1", artifact(kind=ArtifactKind.SYNTHESIS, dependency=(first.id,)))
    decision = ReviewDecision(
        id="review-1",
        run_id="run-1",
        kind=ReviewKind.ARTIFACT,
        outcome=ReviewOutcome.REJECTED,
        reviewer="alice",
        comment="retry",
        created_at=NOW,
        artifact_id=first.id,
    )
    library.add_review(decision)
    library.add_review(
        ReviewDecision(
            id="review-2",
            run_id="run-1",
            kind=ReviewKind.ARTIFACT,
            outcome=ReviewOutcome.APPROVED,
            reviewer="bob",
            comment="fixed",
            created_at=NOW,
            artifact_id=first.id,
            supersedes_id=decision.id,
        )
    )
    assert [item.id for item in library.list_reviews("run-1")] == ["review-1", "review-2"]
    stale = library.delete_source("source-1")
    assert set(stale) == {first.id, derived.id}
    assert library.search("useful") == ()
    with pytest.raises(KeyError):
        library.read_chunks("source-1")


def test_controlled_source_never_persists_body(tmp_path) -> None:
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    controlled = source("source-controlled", policy=AccessPolicy.CONTROLLED)
    library.save_work(Work("work-1", "controlled"))
    library.save_source(controlled)
    assert library.read_chunks("source-controlled") == ()
    assert not list((tmp_path / "content").rglob("*.txt"))


def test_controlled_retry_cannot_remove_an_existing_persisted_body(tmp_path) -> None:
    library = prepared(tmp_path)
    library.save_source(source("source-controlled", policy=AccessPolicy.CONTROLLED))
    assert library.read_chunks("source-1", start=1, limit=1)[0].text == "first paragraph"
