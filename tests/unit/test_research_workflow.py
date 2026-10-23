from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autoresearch.adapters.fake import (
    FakeRuntimeAdapter,
    InMemoryArtifactStore,
    InMemorySourceAdapter,
)
from autoresearch.adapters.sqlite import SqliteResearchLibrary
from autoresearch.application.research import ResearchWorkflow
from autoresearch.application.workflow import InvalidTransitionError
from autoresearch.domain import (
    AccessPolicy,
    ArtifactKind,
    ArtifactSubmission,
    DomainEvent,
    EventKind,
    ResearchProject,
    ResearchRun,
    ReviewKind,
    ReviewOutcome,
    RunStatus,
    SkillVersion,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
    Work,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_library(tmp_path) -> SqliteResearchLibrary:
    return SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")


def make_workflow(
    library: SqliteResearchLibrary, store: InMemoryArtifactStore, *, fail_once_at: str | None = None
) -> ResearchWorkflow:
    def factory(_persist_run: object) -> FakeRuntimeAdapter:
        return FakeRuntimeAdapter(artifacts=store, fail_once_at=fail_once_at)

    return ResearchWorkflow(
        library,
        library.content,
        factory,
        skill_versions=(SkillVersion("triage-sources", "fake-0.1.0"),),
    )


def start_run(wf: ResearchWorkflow) -> tuple[ResearchProject, ResearchRun]:
    project = wf.create_project(name="Agent evolution", description="")
    run = wf.start_run(
        project_id=project.id,
        question="Agent 如何自进化?",
        include=("agent self-evolution",),
        source_kinds=(),
        max_candidates=10,
        max_duration_seconds=1234,
    )
    return project, run


def seed_overview(library: SqliteResearchLibrary, run_id: str) -> None:
    library.save_work(Work("work-seed", "Seed work"))
    library.save_source(
        SourceDocument(
            source_version=SourceVersion(
                id="sv-seed",
                work_id="work-seed",
                source_ref=SourceRef(SourceKind.ARXIV, "arxiv:seed"),
                canonical_url="https://arxiv.org/abs/seed",
                retrieved_at=NOW,
                content_hash="s".rjust(64, "a"),
                access_policy=AccessPolicy.PERSIST,
            ),
            media_type="text/plain",
            text="first\nsecond",
            chunks=("first", "second"),
        )
    )
    library.submit(
        run_id,
        ArtifactSubmission(
            kind=ArtifactKind.OVERVIEW,
            work_id="work-seed",
            markdown="Seeded overview",
            structured={
                "work_id": "work-seed",
                "title": "Seed work",
                "conclusion": "A seeded result.",
                "relation": "Direct evidence.",
                "canonical_url": "https://arxiv.org/abs/seed",
                "tags": ["agent"],
                "scores": {
                    "relevance": 5,
                    "credibility": 4,
                    "evidence_strength": 4,
                    "novelty": 3,
                    "timeliness": 4,
                    "reproducibility": 3,
                    "potential_value": 5,
                },
                "recommendation": "select",
            },
            evidence_ids=("sv-seed#chunk-1",),
            warnings=(),
            skill_name="triage-sources",
            skill_version="1.0.0",
        ),
    )


def test_create_project_persists(tmp_path) -> None:
    library = make_library(tmp_path)
    wf = make_workflow(library, InMemoryArtifactStore())

    project = wf.create_project(name="Agent evolution", description="lab")

    assert library.get_project(project.id) == project


def test_start_run_persists_run_spec_events_and_overviews(tmp_path) -> None:
    library = make_library(tmp_path)
    store = InMemoryArtifactStore()
    wf = make_workflow(library, store)

    _, run = start_run(wf)

    assert run.status is RunStatus.REVIEW_REQUIRED
    assert run.checkpoint == "overviews_ready"
    spec = library.get_run_spec(run.id)
    assert spec.plan.question == "Agent 如何自进化?"
    assert spec.max_candidates == 10
    assert spec.max_duration_seconds == 1234
    assert library.list_events(run.id).events
    overviews = [a for a in store.list(run.id) if a.submission.kind is ArtifactKind.OVERVIEW]
    expected = {str(c.metadata["work_id"]) for c in InMemorySourceAdapter().discover(spec.plan)}
    assert {a.submission.work_id for a in overviews} == expected
    assert len(overviews) == 3


def test_resume_without_selection_fails(tmp_path) -> None:
    library = make_library(tmp_path)
    wf = make_workflow(library, InMemoryArtifactStore())
    _, run = start_run(wf)

    with pytest.raises(InvalidTransitionError, match="selection"):
        make_workflow(library, InMemoryArtifactStore()).resume_run(run.id)


def test_record_selection_persists_decision_and_pauses(tmp_path) -> None:
    library = make_library(tmp_path)
    wf = make_workflow(library, InMemoryArtifactStore())
    _, run = start_run(wf)

    decision = wf.record_selection(
        run.id, work_ids=("work-self-refine",), reviewer="me", comment="ok"
    )

    assert decision.kind is ReviewKind.SOURCE
    assert decision.outcome is ReviewOutcome.APPROVED
    source_reviews = [r for r in library.list_reviews(run.id) if r.kind is ReviewKind.SOURCE]
    assert source_reviews[-1].work_ids == ("work-self-refine",)
    persisted = library.get_run(run.id)
    assert persisted.status is RunStatus.PAUSED
    assert persisted.checkpoint == "overviews_ready"


def test_resume_generates_only_selected_analyses(tmp_path) -> None:
    library = make_library(tmp_path)
    wf = make_workflow(library, InMemoryArtifactStore())
    _, run = start_run(wf)
    wf.record_selection(run.id, work_ids=("work-self-refine",), reviewer="me")

    store = InMemoryArtifactStore()
    resumed = make_workflow(library, store).resume_run(run.id)

    assert resumed.status is RunStatus.REVIEW_REQUIRED
    assert resumed.checkpoint == "analyses_ready"
    analyses = [a for a in store.list(run.id) if a.submission.kind is ArtifactKind.ANALYSIS]
    assert {a.submission.work_id for a in analyses} == {"work-self-refine"}


def test_final_review_reject_then_approve(tmp_path) -> None:
    library = make_library(tmp_path)
    wf = make_workflow(library, InMemoryArtifactStore())
    _, run = start_run(wf)
    wf.record_selection(run.id, work_ids=("work-self-refine",), reviewer="me")
    wf.resume_run(run.id)

    reject = wf.record_final_review(run.id, approved=False, reviewer="me")
    assert reject.outcome is ReviewOutcome.CHANGES_REQUESTED
    assert library.get_run(run.id).status is RunStatus.REVIEW_REQUIRED

    approve = wf.record_final_review(run.id, approved=True, reviewer="me")
    assert approve.outcome is ReviewOutcome.APPROVED
    assert library.get_run(run.id).status is RunStatus.PAUSED


def test_resume_requires_final_approval_then_completes(tmp_path) -> None:
    library = make_library(tmp_path)
    store = InMemoryArtifactStore()
    wf = make_workflow(library, store)
    _, run = start_run(wf)
    wf.record_selection(run.id, work_ids=("work-self-refine",), reviewer="me")
    wf.resume_run(run.id)

    fresh = make_workflow(library, store)
    with pytest.raises(InvalidTransitionError, match="final human approval"):
        fresh.resume_run(run.id)

    fresh.record_final_review(run.id, approved=True, reviewer="me")
    completed = fresh.resume_run(run.id)

    assert completed.status is RunStatus.COMPLETED
    assert completed.checkpoint == "completed"
    syntheses = [a for a in store.list(run.id) if a.submission.kind is ArtifactKind.SYNTHESIS]
    assert syntheses and syntheses[0].submission.work_id is None
    assert all(evidence.endswith("#chunk-1") for evidence in syntheses[0].submission.evidence_ids)


def test_cancel_then_resume_fails(tmp_path) -> None:
    library = make_library(tmp_path)
    wf = make_workflow(library, InMemoryArtifactStore())
    _, run = start_run(wf)

    cancelled = wf.cancel_run(run.id)

    assert cancelled.status is RunStatus.CANCELLED
    with pytest.raises(InvalidTransitionError):
        wf.cancel_run(run.id)
    with pytest.raises(InvalidTransitionError):
        make_workflow(library, InMemoryArtifactStore()).resume_run(run.id)


def test_failure_recovery_resumes_from_checkpoint(tmp_path) -> None:
    library = make_library(tmp_path)
    failing = make_workflow(library, InMemoryArtifactStore(), fail_once_at="analyze_selected")
    _, run = start_run(failing)
    failing.record_selection(run.id, work_ids=("work-self-refine",), reviewer="me")

    failed = failing.resume_run(run.id)

    assert failed.status is RunStatus.FAILED
    assert failed.checkpoint == "overviews_ready"
    assert any(e.kind is EventKind.STEP_FAILED for e in library.list_events(run.id).events)

    recovered = make_workflow(library, InMemoryArtifactStore())
    resumed = recovered.resume_run(run.id)
    assert resumed.status is RunStatus.REVIEW_REQUIRED
    assert resumed.checkpoint == "analyses_ready"

    recovered.record_final_review(run.id, approved=True, reviewer="me")
    completed = recovered.resume_run(run.id)

    assert completed.status is RunStatus.COMPLETED
    sequences = [e.sequence for e in library.list_events(run.id).events]
    assert sequences == list(range(len(sequences)))


def test_event_replay_is_idempotent(tmp_path) -> None:
    library = make_library(tmp_path)
    store = InMemoryArtifactStore()
    wf = make_workflow(library, store)
    _, run = start_run(wf)
    wf.record_selection(run.id, work_ids=("work-self-refine",), reviewer="me")

    make_workflow(library, store).resume_run(run.id)
    second = make_workflow(library, store)
    second.record_final_review(run.id, approved=True, reviewer="me")
    make_workflow(library, store).resume_run(run.id)

    events = library.list_events(run.id).events
    assert [e.sequence for e in events] == list(range(len(events)))
    assert len({e.sequence for e in events}) == len(events)


def test_status_fields(tmp_path) -> None:
    library = make_library(tmp_path)
    wf = make_workflow(library, InMemoryArtifactStore())
    _, run = start_run(wf)
    wf.record_selection(run.id, work_ids=("work-self-refine",), reviewer="me")
    seed_overview(library, run.id)
    library.append_event(
        DomainEvent(
            id="event-fail",
            run_id=run.id,
            sequence=999,
            kind=EventKind.STEP_FAILED,
            occurred_at=NOW,
            data={"step": "collect", "error": "boom"},
        )
    )

    view = wf.status(run.id)

    assert view.run.id == run.id
    assert view.spec.plan.question == "Agent 如何自进化?"
    assert view.artifact_counts[ArtifactKind.OVERVIEW] == 1
    assert view.stale_artifact_count == 0
    assert view.latest_reviews and view.latest_reviews[-1].kind is ReviewKind.SOURCE
    assert any("步骤失败" in note for note in view.warnings)


def test_export_delegates(tmp_path) -> None:
    library = make_library(tmp_path)
    wf = make_workflow(library, InMemoryArtifactStore())
    _, run = start_run(wf)
    destination = tmp_path / "out"

    result = wf.export_run(run.id, destination)

    assert result.destination == destination
    assert result.manifest_path.is_file()
    assert result.artifact_count == 0
