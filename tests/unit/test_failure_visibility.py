"""Failure-visibility tests: every failure/warning category must be visible in
both ``run status`` output and the exported ``warnings.md``.

The test builds a real :class:`SqliteResearchLibrary` plus a ``ContentStore``,
seeds a run and an event/artifact stream covering six warning categories, then
asserts each category's keyword appears in ``ResearchWorkflow.status`` warnings,
the exported ``warnings.md``, and (for the human CLI path) ``run status`` stdout.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import autoresearch.cli as cli
from autoresearch.adapters.fake import FakeRuntimeAdapter
from autoresearch.adapters.sqlite import SqliteResearchLibrary
from autoresearch.application.research import ResearchWorkflow
from autoresearch.domain import (
    AccessPolicy,
    ArtifactKind,
    ArtifactSubmission,
    DomainEvent,
    EventKind,
    ResearchPlan,
    ResearchProject,
    ResearchRun,
    RunSpec,
    RunStatus,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
    Work,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
TEXT = "first paragraph\nsecond paragraph"
DIGEST = hashlib.sha256(TEXT.encode()).hexdigest()

# One keyword per warning category; every keyword must show up in all three
# surfaces (status view, warnings.md, and human-readable CLI status).
KEYWORDS = ("collect_sources", "限流", "正文缺失", "解析", "模型", "工件警告")


def _run() -> ResearchRun:
    return ResearchRun(
        id="run-failures",
        project_id="project-failures",
        status=RunStatus.RUNNING,
        plan=ResearchPlan(question="q", include_terms=("agent",)),
        workflow_version="research-v1",
        created_at=NOW,
        updated_at=NOW,
        checkpoint="overviews_ready",
    )


def _source(
    source_id: str,
    *,
    work_id: str,
    content_hash: str = DIGEST,
) -> SourceDocument:
    return SourceDocument(
        source_version=SourceVersion(
            id=source_id,
            work_id=work_id,
            source_ref=SourceRef(SourceKind.ARXIV, f"arxiv:{source_id}"),
            canonical_url=f"https://arxiv.org/abs/{source_id}",
            retrieved_at=NOW,
            content_hash=content_hash,
            access_policy=AccessPolicy.PERSIST,
        ),
        media_type="text/plain",
        text=TEXT,
        chunks=("first paragraph", "second paragraph"),
    )


def _event(run_id: str, sequence: int, *, kind: EventKind, data: dict) -> DomainEvent:
    return DomainEvent(
        id=f"event-{sequence}",
        run_id=run_id,
        sequence=sequence,
        kind=kind,
        occurred_at=NOW,
        data=data,
    )


def _prepare(tmp_path: Path) -> tuple[SqliteResearchLibrary, str]:
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    library.save_project(ResearchProject("project-failures", "Failures"))
    run = _run()
    library.save_run(run)
    library.save_run_spec(
        RunSpec(
            project_id=run.project_id,
            plan=run.plan,
            workflow_version=run.workflow_version,
            skill_versions={},
            max_duration_seconds=1800,
            max_candidates=20,
        ),
        run.id,
    )
    library.save_work(Work("work-1", "Self refining agents"))
    library.save_source(_source("source-1", work_id="work-1"))
    library.save_run_source(run.id, "source-1")
    return library, run.id


def _seed_failures(library: SqliteResearchLibrary, run_id: str) -> None:
    # 1. A single source collection failure (STEP_FAILED).
    library.append_event(
        _event(
            run_id,
            1,
            kind=EventKind.STEP_FAILED,
            data={
                "step": "collect_sources",
                "category": "source_fetch",
                "code": "fetch_failed",
                "message": "failed to fetch source",
                "source": "https://arxiv.org/abs/1",
                "error": "collect failure",
            },
        )
    )
    # 2. Rate limiting on a later step.
    library.append_event(
        _event(
            run_id,
            2,
            kind=EventKind.STEP_STARTED,
            data={"step": "triage", "rate_limit": True},
        )
    )
    # 3. A PERSIST source whose body blob is missing from the content store.
    library.save_source(_source("source-2", work_id="work-2", content_hash="b" * 64))
    library.save_run_source(run_id, "source-2")
    # 4. A parse failure while analyzing a selected source.
    library.append_event(
        _event(
            run_id,
            3,
            kind=EventKind.STEP_FAILED,
            data={
                "step": "analyze_selected",
                "code": "parse_error",
                "message": "malformed structured output",
                "error": "解析失败: invalid JSON payload",
            },
        )
    )
    # 5. A model/tool failure during synthesis.
    library.append_event(
        _event(
            run_id,
            4,
            kind=EventKind.STEP_FAILED,
            data={
                "step": "synthesize",
                "code": "pi.command_failed",
                "message": "model returned an error",
                "error": "模型调用失败: pi.command_failed",
            },
        )
    )
    # 6. An artifact submitted with a note attached.
    library.submit(
        run_id,
        ArtifactSubmission(
            kind=ArtifactKind.OVERVIEW,
            work_id="work-1",
            markdown="A useful result",
            structured={
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
            },
            evidence_ids=("source-1#chunk-1",),
            warnings=("credibility 评分偏低",),
            skill_name="triage-sources",
            skill_version="1.0.0",
        ),
    )


def _workflow(library: SqliteResearchLibrary) -> ResearchWorkflow:
    return ResearchWorkflow(library, library.content, lambda _: FakeRuntimeAdapter())


def test_failure_visibility_surfaces_every_category(tmp_path: Path) -> None:
    library, run_id = _prepare(tmp_path)
    _seed_failures(library, run_id)
    workflow = _workflow(library)

    status_warnings = workflow.status(run_id).warnings
    destination = tmp_path / "export"
    workflow.export_run(run_id, destination)
    warnings_md = (destination / "warnings.md").read_text(encoding="utf-8")

    for keyword in KEYWORDS:
        assert any(keyword in note for note in status_warnings), (
            f"{keyword!r} missing from status().warnings: {status_warnings}"
        )
        assert keyword in warnings_md, f"{keyword!r} missing from warnings.md"


def test_cli_run_status_shows_failure_warnings(tmp_path, capsys, monkeypatch) -> None:
    library, run_id = _prepare(tmp_path)
    _seed_failures(library, run_id)

    def build(args: object) -> ResearchWorkflow:
        del args
        return _workflow(library)

    monkeypatch.setattr(cli, "_build_workflow", build)

    code = cli.main(["run", "status", run_id])
    captured = capsys.readouterr()

    assert code == 0
    for keyword in KEYWORDS:
        assert keyword in captured.out, f"{keyword!r} missing from CLI status stdout"
