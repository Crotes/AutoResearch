from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from autoresearch.adapters.sqlite import SqliteResearchLibrary
from autoresearch.application.export import export_run
from autoresearch.domain.events import DomainEvent, EventKind
from autoresearch.domain.library import ResearchProject, Work
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
TEXT = "first paragraph\nsecond paragraph"
DIGEST = hashlib.sha256(TEXT.encode()).hexdigest()


def run() -> ResearchRun:
    return ResearchRun(
        id="run-1",
        project_id="project-1",
        status=RunStatus.RUNNING,
        plan=ResearchPlan(question="q", include_terms=("agent",)),
        workflow_version="w1",
        created_at=NOW,
        updated_at=NOW,
        checkpoint="overviews_ready",
    )


def source(
    source_id: str = "source-1",
    *,
    work_id: str = "work-1",
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


def artifact(
    *,
    kind: ArtifactKind = ArtifactKind.OVERVIEW,
    evidence: str = "source-1#chunk-1",
    work_id: str = "work-1",
    warnings: tuple[str, ...] = (),
) -> ArtifactSubmission:
    if kind is ArtifactKind.OVERVIEW:
        skill_name = "triage-sources"
        structured = {
            "work_id": work_id,
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
            "work_id": work_id,
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
            "categories": [{"name": "reflection", "origin": "emergent", "work_ids": [work_id]}],
            "method_comparison": ["Feedback differs in timing"],
            "consensus": ["Evaluation matters"],
            "conflicts": [],
            "evidence_gaps": ["Long-term evidence"],
            "research_gaps": ["Stable adaptation"],
            "follow_up_questions": ["How should feedback be weighted?"],
        }
    return ArtifactSubmission(
        kind=kind,
        work_id=work_id,
        markdown="A useful result",
        structured=structured,
        evidence_ids=(evidence,),
        warnings=warnings,
        skill_name=skill_name,
        skill_version="1.0.0",
        dependency_artifact_ids=(),
    )


def event(
    sequence: int,
    *,
    kind: EventKind | None = None,
    data: dict | None = None,
) -> DomainEvent:
    return DomainEvent(
        id=f"event-{sequence}",
        run_id="run-1",
        sequence=sequence,
        kind=kind or (EventKind.RUN_STARTED if sequence == 0 else EventKind.STEP_STARTED),
        occurred_at=NOW,
        data={"step": sequence} if data is None else data,
    )


def prepared(tmp_path: Path) -> SqliteResearchLibrary:
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    library.save_project(ResearchProject("project-1", "Lab"))
    library.save_run(run())
    library.save_work(Work("work-1", "Self refining agents"))
    library.save_source(source())
    library.save_run_source("run-1", "source-1")
    return library


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_export_writes_complete_bundle(tmp_path: Path) -> None:
    library = prepared(tmp_path)
    library.submit("run-1", artifact())
    library.submit("run-1", artifact(kind=ArtifactKind.ANALYSIS))
    library.submit("run-1", artifact(kind=ArtifactKind.SYNTHESIS))
    library.append_event(event(0))
    library.append_event(event(1))
    destination = tmp_path / "out"

    result = export_run(library, library.content, "run-1", destination)

    assert result.destination == destination
    assert result.manifest_path == destination / "manifest.json"
    assert result.artifact_count == 3
    assert result.stale_artifact_count == 0
    assert result.warnings == ()
    for name in ("run.json", "events.jsonl", "manifest.json", "warnings.md", "evidence/index.json"):
        assert (destination / name).is_file(), name

    run_json = read_json(destination / "run.json")
    assert run_json["id"] == "run-1"
    assert run_json["question"] == "q"
    assert run_json["checkpoint"] == "overviews_ready"
    assert run_json["spec"]["max_candidates"] == 20

    manifest = read_json(result.manifest_path)
    assert manifest["format_version"] == "1"
    assert manifest["counts"] == {"artifacts": 3, "stale_artifacts": 0, "events": 2, "sources": 1}
    paths = {entry["path"] for entry in manifest["artifacts"]}
    assert "artifacts/synthesis.md" in paths
    assert any(path.startswith("artifacts/overviews/") for path in paths)
    assert any(path.startswith("artifacts/analyses/") for path in paths)
    for entry in manifest["artifacts"]:
        assert (destination / entry["path"]).is_file()
        assert entry["policy"] == "persist"
        assert entry["validity"] == "valid"

    evidence = read_json(destination / "evidence" / "index.json")
    assert evidence[0]["id"] == "source-1"
    assert evidence[0]["title"] == "Self refining agents"
    assert evidence[0]["content_available"] is True


def test_export_marks_stale_artifacts(tmp_path: Path) -> None:
    library = prepared(tmp_path)
    library.submit("run-1", artifact())
    library.delete_source("source-1")
    destination = tmp_path / "out"

    result = export_run(library, library.content, "run-1", destination)

    assert result.artifact_count == 0
    assert result.stale_artifact_count == 1
    manifest = read_json(result.manifest_path)
    assert manifest["stale_artifacts"][0]["validity"] == "stale"
    assert manifest["stale_artifacts"][0]["reason"] is None
    assert any("stale" in note for note in result.warnings)
    evidence = read_json(destination / "evidence" / "index.json")
    assert evidence[0]["id"] == "source-1"
    assert evidence[0]["title"] is None
    assert any("source-1" in note for note in result.warnings)


def test_export_withholds_body_for_controlled_and_metadata_only(tmp_path: Path) -> None:
    library = prepared(tmp_path)
    library.save_source(source("source-2"))
    library.save_source(source("source-3"))
    library.save_run_source("run-1", "source-2")
    library.save_run_source("run-1", "source-3")
    library.connection.execute(
        "UPDATE source_versions SET access_policy='controlled' WHERE id='source-2'"
    )
    library.connection.execute(
        "UPDATE source_versions SET access_policy='metadata_only' WHERE id='source-3'"
    )
    library.submit("run-1", artifact(evidence="source-2#chunk-1"))
    library.submit("run-1", artifact(evidence="source-3#chunk-1"))
    destination = tmp_path / "out"

    result = export_run(library, library.content, "run-1", destination)

    assert result.artifact_count == 2
    manifest = read_json(result.manifest_path)
    policies = {entry["evidence_ids"][0]: entry for entry in manifest["artifacts"]}
    assert policies["source-2#chunk-1"]["policy"] == "controlled"
    assert policies["source-3#chunk-1"]["policy"] == "metadata_only"
    assert all(entry["path"] is None for entry in manifest["artifacts"])
    written = list(destination.rglob("*.md"))
    assert [path.name for path in written] == ["warnings.md"]


def test_export_warns_when_source_body_is_missing(tmp_path: Path) -> None:
    library = prepared(tmp_path)
    library.save_source(source("source-2", content_hash="b" * 64))
    library.save_run_source("run-1", "source-2")
    library.submit("run-1", artifact(evidence="source-2#chunk-1"))
    destination = tmp_path / "out"

    result = export_run(library, library.content, "run-1", destination)

    assert any("正文缺失" in note and "source-2" in note for note in result.warnings)
    evidence = read_json(destination / "evidence" / "index.json")
    entries = {entry["id"]: entry for entry in evidence}
    assert entries["source-1"]["content_available"] is True
    assert entries["source-2"]["content_available"] is False
    warnings_md = (destination / "warnings.md").read_text(encoding="utf-8")
    assert "正文缺失" in warnings_md


def test_export_sanitizes_artifact_filenames(tmp_path: Path) -> None:
    library = prepared(tmp_path)
    nasty = 'A/B .. C:\\name with spaces 中文 "quoted" ' + "x" * 120
    library.save_work(Work("work-2", nasty))
    library.save_source(source("source-2", work_id="work-2"))
    library.save_run_source("run-1", "source-2")
    library.submit("run-1", artifact(evidence="source-2#chunk-1", work_id="work-2"))
    destination = tmp_path / "out"

    result = export_run(library, library.content, "run-1", destination)

    manifest = read_json(result.manifest_path)
    relative = manifest["artifacts"][0]["path"]
    stem = Path(relative).stem
    assert relative.startswith("artifacts/overviews/")
    assert ".." not in relative
    assert stem == stem.encode("ascii", "ignore").decode()
    assert not any(char in stem for char in '/\\ "')
    assert len(stem) <= 80
    assert (destination / relative).is_file()


def test_events_jsonl_lines_match_library_events(tmp_path: Path) -> None:
    library = prepared(tmp_path)
    library.append_event(event(0))
    library.append_event(
        event(1, kind=EventKind.STEP_FAILED, data={"step": "collect", "error": "boom"})
    )
    library.append_event(event(2, data={"step": "triage", "rate_limit": True}))
    destination = tmp_path / "out"

    result = export_run(library, library.content, "run-1", destination)

    lines = (destination / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    records = [json.loads(line) for line in lines]
    assert [record["sequence"] for record in records] == [0, 1, 2]
    assert records[1]["kind"] == str(EventKind.STEP_FAILED)
    assert all(record["run_id"] == "run-1" for record in records)
    assert any("步骤失败" in note for note in result.warnings)
    assert any("限流" in note for note in result.warnings)


def test_warnings_md_written_even_without_warnings(tmp_path: Path) -> None:
    library = prepared(tmp_path)
    destination = tmp_path / "out"

    result = export_run(library, library.content, "run-1", destination)

    assert result.warnings == ()
    warnings_md = (destination / "warnings.md").read_text(encoding="utf-8")
    assert "无警告" in warnings_md


def test_reexport_overwrites_previous_bundle(tmp_path: Path) -> None:
    library = prepared(tmp_path)
    library.submit("run-1", artifact())
    library.submit("run-1", artifact(kind=ArtifactKind.SYNTHESIS))
    destination = tmp_path / "out"

    first = export_run(library, library.content, "run-1", destination)
    snapshot = {
        path.relative_to(destination): path.read_bytes()
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    second = export_run(library, library.content, "run-1", destination)

    assert second.artifact_count == first.artifact_count == 2
    assert second.warnings == first.warnings
    replay = {
        path.relative_to(destination): path.read_bytes()
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    assert replay == snapshot
