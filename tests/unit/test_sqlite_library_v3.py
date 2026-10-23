from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from autoresearch.adapters.sqlite import SqliteResearchLibrary, migrations
from autoresearch.domain.events import DomainEvent, EventKind
from autoresearch.domain.library import ResearchProject, SkillVersion, Work
from autoresearch.domain.models import (
    AccessPolicy,
    ArtifactKind,
    ArtifactSubmission,
    ResearchPlan,
    ResearchRun,
    RunSpec,
    RunStatus,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def run(run_id: str = "run-1", *, checkpoint: str | None = None) -> ResearchRun:
    return ResearchRun(
        id=run_id,
        project_id="project-1",
        status=RunStatus.RUNNING,
        plan=ResearchPlan(question="q", include_terms=("agent",)),
        workflow_version="w1",
        created_at=NOW,
        updated_at=NOW,
        checkpoint=checkpoint,
    )


def spec() -> RunSpec:
    return RunSpec(
        project_id="project-1",
        plan=ResearchPlan(
            question="How do agents self-improve?",
            include_terms=("agent", "self-improvement"),
            exclude_terms=("marketing",),
            source_kinds=(SourceKind.ARXIV,),
            seed_urls=("https://arxiv.org/abs/1",),
        ),
        workflow_version="research-v1",
        skill_versions={"collect-sources": "1.2.0", "triage-sources": "0.9.1"},
        max_duration_seconds=3600,
        max_candidates=42,
    )


def source(source_id: str = "source-1") -> SourceDocument:
    return SourceDocument(
        source_version=SourceVersion(
            id=source_id,
            work_id="work-1",
            source_ref=SourceRef(SourceKind.ARXIV, f"arxiv:{source_id}"),
            canonical_url=f"https://arxiv.org/abs/{source_id}",
            retrieved_at=NOW,
            content_hash=source_id.rjust(64, "a"),
            access_policy=AccessPolicy.PERSIST,
        ),
        media_type="text/plain",
        text="first paragraph\nsecond paragraph",
        chunks=("first paragraph", "second paragraph"),
    )


def event(run_id: str = "run-1", sequence: int = 0, event_id: str | None = None) -> DomainEvent:
    return DomainEvent(
        id=event_id or f"event-{sequence}",
        run_id=run_id,
        sequence=sequence,
        kind=EventKind.RUN_STARTED if sequence == 0 else EventKind.STEP_STARTED,
        occurred_at=NOW,
        data={"step": sequence},
    )


def artifact(
    *,
    kind: ArtifactKind = ArtifactKind.OVERVIEW,
    evidence: str = "source-1#chunk-1",
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
        dependency_artifact_ids=(),
    )


def prepared(tmp_path) -> SqliteResearchLibrary:
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    library.save_project(ResearchProject("project-1", "Lab"))
    library.save_run(run())
    library.save_work(Work("work-1", "Self refining agents"))
    library.save_source(source())
    return library


def test_version_two_database_migrates_without_losing_data(tmp_path, monkeypatch) -> None:
    database = tmp_path / "library.sqlite"
    content = tmp_path / "content"
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 2)
    library = SqliteResearchLibrary(database, content)
    library.save_project(ResearchProject("project-1", "Lab"))
    library.connection.execute(
        "INSERT INTO runs(id,project_id,status,plan_json,workflow_version,created_at,"
        "updated_at,checkpoint) VALUES (?,?,?,?,?,?,?,?)",
        (
            "run-1",
            "project-1",
            "paused",
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
            "overviews_ready",
        ),
    )
    library.save_work(Work("work-1", "Self refining agents"))
    library.save_source(source())
    library.close()
    monkeypatch.undo()

    migrated = SqliteResearchLibrary(database, content)

    paused = run(checkpoint="overviews_ready")
    assert migrated.get_run("run-1") == ResearchRun(
        id=paused.id,
        project_id=paused.project_id,
        status=RunStatus.PAUSED,
        plan=paused.plan,
        workflow_version=paused.workflow_version,
        created_at=paused.created_at,
        updated_at=paused.updated_at,
        checkpoint="overviews_ready",
    )
    assert migrated.read_chunks("source-1", start=1, limit=1)[0].text == "first paragraph"
    assert migrated.get_run_spec("run-1") == RunSpec(
        project_id="project-1",
        plan=paused.plan,
        workflow_version="w1",
        skill_versions={},
        max_duration_seconds=1800,
        max_candidates=20,
    )
    migrated.append_event(event())
    migrated.save_run_source("run-1", "source-1")
    assert migrated.list_events("run-1").events == (event(),)
    assert migrated.list_run_sources("run-1") == ("source-1",)


def test_run_spec_roundtrip_survives_reopen(tmp_path) -> None:
    database = tmp_path / "library.sqlite"
    library = SqliteResearchLibrary(database, tmp_path / "content")
    expected = spec()
    library.save_run(
        run(),
        skill_versions=[
            SkillVersion("collect-sources", "1.2.0"),
            SkillVersion("triage-sources", "0.9.1"),
        ],
        max_duration_seconds=3600,
        max_candidates=42,
    )
    library.save_run_spec(expected, "run-1")
    library.close()

    reopened = SqliteResearchLibrary(database, tmp_path / "content")

    assert reopened.get_run_spec("run-1") == expected
    with pytest.raises(KeyError):
        reopened.get_run_spec("run-missing")
    with pytest.raises(KeyError):
        reopened.save_run_spec(expected, "run-missing")


def test_save_run_without_spec_keeps_default_budgets(tmp_path) -> None:
    library = prepared(tmp_path)

    restored = library.get_run_spec("run-1")

    assert restored.skill_versions == {}
    assert restored.max_duration_seconds == 1800
    assert restored.max_candidates == 20
    assert restored.plan == run().plan


def test_events_append_in_order_and_replay_is_idempotent(tmp_path) -> None:
    library = prepared(tmp_path)
    first, second = event(sequence=0), event(sequence=1)
    library.append_event(first)
    library.append_event(second)
    library.append_event(event(sequence=1, event_id="event-duplicate"))

    page = library.list_events("run-1")

    assert page.events == (first, second)
    assert page.next_cursor == 2


def test_list_events_cursor_pages_forward(tmp_path) -> None:
    library = prepared(tmp_path)
    for sequence in range(3):
        library.append_event(event(sequence=sequence))

    assert library.list_events("run-1", cursor=0).next_cursor == 3
    middle = library.list_events("run-1", cursor=1)
    assert [item.sequence for item in middle.events] == [1, 2]
    assert middle.next_cursor == 3
    drained = library.list_events("run-1", cursor=3)
    assert drained.events == ()
    assert drained.next_cursor == 3
    with pytest.raises(ValueError):
        library.list_events("run-1", cursor=-1)


def test_run_source_links_roundtrip_and_deduplicate(tmp_path) -> None:
    library = prepared(tmp_path)
    library.save_source(source("source-2"))
    library.save_run(run("run-2"))

    library.save_run_source("run-1", "source-1")
    library.save_run_source("run-1", "source-2")
    library.save_run_source("run-1", "source-1")
    library.save_run_source("run-2", "source-2")

    assert library.list_run_sources("run-1") == ("source-1", "source-2")
    assert library.list_run_sources("run-2") == ("source-2",)
    assert library.list_run_sources("run-missing") == ()


def test_list_artifacts_filters_kind_and_stale_per_run(tmp_path) -> None:
    library = prepared(tmp_path)
    library.save_run(run("run-2"))
    overview = library.submit(
        "run-1", artifact(kind=ArtifactKind.OVERVIEW, evidence="source-1#chunk-1")
    )
    library.submit("run-1", artifact(kind=ArtifactKind.ANALYSIS, evidence="source-1#chunk-2"))
    library.submit("run-2", artifact(kind=ArtifactKind.OVERVIEW, evidence="source-1#chunk-1"))

    run_one = library.list_artifacts("run-1")
    assert [item.submission.kind for item in run_one] == [
        ArtifactKind.OVERVIEW,
        ArtifactKind.ANALYSIS,
    ]
    assert [item.submission.kind for item in library.list_artifacts("run-2")] == [
        ArtifactKind.OVERVIEW
    ]
    analyses = library.list_artifacts("run-1", kind=ArtifactKind.ANALYSIS)
    assert [item.id for item in analyses] == [run_one[1].id]

    library.delete_source("source-1")
    assert library.list_artifacts("run-1") == ()
    everything = library.list_artifacts("run-1", include_stale=True)
    assert {item.id for item in everything} == {overview.id, run_one[1].id}
