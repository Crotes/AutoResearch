from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
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
    if kind is ArtifactKind.OVERVIEW:
        skill_name = "triage-sources"
        structured = {
            "work_id": "work-1",
            "title": "Self refining agents",
            "conclusion": "The method uses iterative feedback.",
            "relation": "Directly studies agent self-improvement.",
            "canonical_url": "https://arxiv.org/abs/1",
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
        }
    elif kind is ArtifactKind.ANALYSIS:
        skill_name = "analyze-source"
        structured = {
            "work_id": "work-1",
            "research_problem": "How agents improve",
            "method": "Iterative feedback",
            "experiments": "A fixed benchmark",
            "results": "Improved success",
            "limitations": ["Small evaluation"],
            "applicability": "Tool-using agents",
            "reproducibility": "Code available",
            "relation_to_question": "Direct evidence",
        }
    else:
        skill_name = "synthesize-topic"
        structured = {
            "categories": [{"name": "reflection", "origin": "emergent", "work_ids": ["work-1"]}],
            "method_comparison": ["Feedback differs in timing"],
            "consensus": ["Evaluation matters"],
            "conflicts": [],
            "evidence_gaps": ["Long-term evidence"],
            "research_gaps": ["Stable adaptation"],
            "follow_up_questions": ["How should feedback be weighted?"],
        }
    return ArtifactSubmission(
        kind=kind,
        work_id="work-1",
        markdown="A useful result",
        structured=structured,
        evidence_ids=(evidence,),
        warnings=(),
        skill_name=skill_name,
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


def test_stale_artifact_cannot_be_used_as_a_new_dependency(tmp_path) -> None:
    library = prepared(tmp_path)
    stale_artifact = library.submit("run-1", artifact())
    library.delete_source("source-1")
    library.save_work(Work("work-2", "Independent evidence"))
    valid_source = replace(
        source("source-2"),
        source_version=replace(
            source("source-2").source_version,
            work_id="work-2",
            source_ref=SourceRef(SourceKind.ARXIV, "arxiv:2"),
            canonical_url="https://arxiv.org/abs/2",
            content_hash="b" * 64,
        ),
    )
    library.save_source(valid_source)

    with pytest.raises(ValueError, match="stale"):
        library.submit(
            "run-1",
            artifact(
                kind=ArtifactKind.SYNTHESIS,
                evidence="source-2#chunk-1",
                dependency=(stale_artifact.id,),
            ),
        )


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


def test_persist_upgrade_updates_source_policy_and_survives_reopen(tmp_path) -> None:
    database = tmp_path / "library.sqlite"
    content = tmp_path / "content"
    library = SqliteResearchLibrary(database, content)
    library.save_work(Work("work-1", "Source"))
    library.save_source(source(policy=AccessPolicy.CONTROLLED))
    library.save_source(source(policy=AccessPolicy.PERSIST))
    library.close()

    reopened = SqliteResearchLibrary(database, content)
    restored = reopened.get_source("source-1")

    assert restored.access_policy is AccessPolicy.PERSIST
    assert reopened.read_chunks("source-1", start=1, limit=1)[0].text == "first paragraph"


def test_business_state_and_selection_review_can_be_reloaded(tmp_path) -> None:
    database = tmp_path / "library.sqlite"
    library = SqliteResearchLibrary(database, tmp_path / "content")
    project = ResearchProject("project-1", "Agent evolution", "Long-lived topic")
    work = Work("work-1", "Self refining agents", ("doi:10.1/abc",), {"year": "2026"})
    paused = ResearchRun(
        id="run-1",
        project_id=project.id,
        status=RunStatus.PAUSED,
        plan=ResearchPlan(question="q", include_terms=("agent",)),
        workflow_version="research-v1",
        created_at=NOW,
        updated_at=NOW,
        checkpoint="overviews_ready",
    )
    review = ReviewDecision(
        id="review-selection-1",
        run_id=paused.id,
        kind=ReviewKind.SOURCE,
        outcome=ReviewOutcome.APPROVED,
        reviewer="alice",
        comment="Analyze these works",
        created_at=NOW,
        work_ids=(work.id,),
    )
    library.save_project(project)
    library.save_work(work)
    library.save_run(paused)
    library.add_review(review)
    library.close()

    reopened = SqliteResearchLibrary(database, tmp_path / "content")

    assert reopened.get_project(project.id) == project
    assert reopened.get_work(work.id) == work
    assert reopened.get_run(paused.id) == paused
    assert reopened.list_reviews(paused.id) == (review,)


def test_version_one_database_is_migrated_without_losing_run_state(tmp_path) -> None:
    database = tmp_path / "library.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES (1, '2026-01-01T00:00:00+00:00');
        CREATE TABLE projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE runs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          status TEXT NOT NULL, plan_json TEXT NOT NULL, workflow_version TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO projects VALUES ('project-1', 'Lab', '');
        """
    )
    connection.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
        (
            "run-1",
            "project-1",
            "running",
            json.dumps(
                {
                    "question": "q",
                    "include_terms": ["agent"],
                    "exclude_terms": [],
                    "languages": ["zh", "en"],
                    "source_kinds": [],
                    "start_date": None,
                    "end_date": None,
                    "seed_urls": [],
                }
            ),
            "w1",
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    connection.commit()
    connection.close()

    library = SqliteResearchLibrary(database, tmp_path / "content")

    assert library.get_run("run-1") == run()


def test_work_identity_deduplicates_different_source_urls(tmp_path) -> None:
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    original = library.save_work(
        Work(
            "work-paper",
            "Self refining agents",
            ("doi:10.1/abc", "url:https://arxiv.org/abs/1"),
        )
    )
    duplicate = library.save_work(
        Work(
            "work-blog",
            "An explanation of self refining agents",
            ("doi:10.1/abc", "url:https://example.org/explanation"),
        )
    )

    assert duplicate.id == original.id == "work-paper"
    assert library.resolve_work("url:https://example.org/explanation") == "work-paper"
    with pytest.raises(KeyError):
        library.get_work("work-blog")


def test_skill_output_schema_is_checked_before_artifact_is_saved(tmp_path) -> None:
    library = prepared(tmp_path)
    invalid = replace(artifact(), structured={"title": "Missing required overview fields"})

    with pytest.raises(ValueError, match="schema"):
        library.submit("run-1", invalid)

    assert library.search("Missing") == ()
