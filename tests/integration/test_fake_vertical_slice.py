from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoresearch.adapters import FakeRuntimeAdapter
from autoresearch.domain import ArtifactKind, ResearchPlan, RunSpec, RunStatus, SourceKind


def make_spec() -> RunSpec:
    return RunSpec(
        project_id="project-agent-evolution",
        plan=ResearchPlan(
            question="Agent 如何自进化?",
            include_terms=("agent self-evolution",),
            source_kinds=(SourceKind.ARXIV, SourceKind.GITHUB, SourceKind.RSS),
        ),
        workflow_version="fake-0.1.0",
        skill_versions={"triage-sources": "fake-0.1.0"},
        max_duration_seconds=60,
        max_candidates=20,
    )


def select_first_two(runtime: FakeRuntimeAdapter, run_id: str) -> tuple[str, ...]:
    work_ids = tuple(
        artifact.submission.work_id
        for artifact in runtime.list_artifacts(run_id)
        if artifact.submission.kind is ArtifactKind.OVERVIEW
        and artifact.submission.work_id is not None
    )
    selected = work_ids[:2]
    runtime.review_selection(run_id, selected)
    return selected


def test_run_pauses_for_selection_before_creating_analysis() -> None:
    runtime = FakeRuntimeAdapter()
    run_id = runtime.start(make_spec())

    run = runtime.inspect(run_id)
    artifacts = runtime.list_artifacts(run_id)

    assert run.status is RunStatus.REVIEW_REQUIRED
    assert run.checkpoint == "overviews_ready"
    assert len(artifacts) == 3
    assert {artifact.submission.kind for artifact in artifacts} == {ArtifactKind.OVERVIEW}
    with pytest.raises(ValueError, match="human selection"):
        runtime.resume(run_id)


def test_selected_works_reach_final_review_and_completion() -> None:
    runtime = FakeRuntimeAdapter()
    run_id = runtime.start(make_spec())
    selected = select_first_two(runtime, run_id)

    runtime.resume(run_id)

    assert runtime.inspect(run_id).status is RunStatus.REVIEW_REQUIRED
    assert runtime.inspect(run_id).checkpoint == "analyses_ready"
    analyses = [
        artifact
        for artifact in runtime.list_artifacts(run_id)
        if artifact.submission.kind is ArtifactKind.ANALYSIS
    ]
    assert {artifact.submission.work_id for artifact in analyses} == set(selected)
    assert (
        sum(
            artifact.submission.kind is ArtifactKind.SYNTHESIS
            for artifact in runtime.list_artifacts(run_id)
        )
        == 1
    )

    runtime.review_final(run_id, approved=True)
    runtime.resume(run_id)

    assert runtime.inspect(run_id).status is RunStatus.COMPLETED
    assert runtime.inspect(run_id).checkpoint == "completed"


def test_failed_step_resumes_from_last_checkpoint() -> None:
    runtime = FakeRuntimeAdapter(fail_once_at="analyze_selected")
    run_id = runtime.start(make_spec())
    select_first_two(runtime, run_id)

    runtime.resume(run_id)

    failed = runtime.inspect(run_id)
    assert failed.status is RunStatus.FAILED
    assert failed.checkpoint == "overviews_ready"
    assert all(
        artifact.submission.kind is ArtifactKind.OVERVIEW
        for artifact in runtime.list_artifacts(run_id)
    )

    runtime.resume(run_id)

    assert runtime.inspect(run_id).checkpoint == "analyses_ready"


def test_cancelled_run_cannot_resume() -> None:
    runtime = FakeRuntimeAdapter()
    run_id = runtime.start(make_spec())
    runtime.cancel(run_id)

    assert runtime.inspect(run_id).status is RunStatus.CANCELLED
    with pytest.raises(ValueError, match="cancelled"):
        runtime.resume(run_id)


def test_export_contains_manifest_sources_events_and_three_layers(tmp_path: Path) -> None:
    runtime = FakeRuntimeAdapter()
    run_id = runtime.start(make_spec())
    select_first_two(runtime, run_id)
    runtime.resume(run_id)
    runtime.review_final(run_id, approved=True)
    runtime.resume(run_id)

    destination = runtime.export(run_id, tmp_path / "export")

    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == run_id
    assert manifest["status"] == "completed"
    assert len(list((destination / "sources").glob("*.md"))) == 3
    assert len(list((destination / "artifacts" / "overviews").glob("*.md"))) == 3
    assert len(list((destination / "artifacts" / "analyses").glob("*.md"))) == 2
    assert (destination / "artifacts" / "synthesis.md").is_file()
    assert (destination / "events.jsonl").read_text(encoding="utf-8").count("\n") > 0
