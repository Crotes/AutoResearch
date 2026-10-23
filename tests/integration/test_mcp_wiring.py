from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from autoresearch.adapters import SqliteResearchLibrary
from autoresearch.adapters.mcp.__main__ import main
from autoresearch.adapters.mcp.server import ResearchToolsServer
from autoresearch.adapters.mcp.tools import TOOL_DEFINITIONS
from autoresearch.adapters.mcp.wiring import (
    CONTENT_ROOT_ENV,
    DATABASE_ENV,
    MODE_ENV,
    RUN_ID_ENV,
    WiringError,
    build_production_server,
)
from autoresearch.application.artifact_policy import PolicyEnforcingArtifacts
from autoresearch.domain import (
    AccessPolicy,
    ResearchPlan,
    ResearchProject,
    ResearchRun,
    RunStatus,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ALL_ENV_VARS = (RUN_ID_ENV, DATABASE_ENV, CONTENT_ROOT_ENV, MODE_ENV)


def call(server: ResearchToolsServer, request_id: int, name: str, arguments: dict) -> dict:
    response = server.handle_line(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
    )
    assert response is not None
    return json.loads(response)["result"]


def call_ok(server: ResearchToolsServer, request_id: int, name: str, arguments: dict) -> dict:
    payload = call(server, request_id, name, arguments)
    assert payload["isError"] is False, payload
    return json.loads(payload["content"][0]["text"])


def make_env(tmp_path, run_id: str = "run-1") -> dict[str, str]:
    return {
        RUN_ID_ENV: run_id,
        DATABASE_ENV: str(tmp_path / "library.sqlite"),
        CONTENT_ROOT_ENV: str(tmp_path / "content"),
        MODE_ENV: "run",
    }


def make_document(source_version_id: str, url: str) -> SourceDocument:
    return SourceDocument(
        source_version=SourceVersion(
            id=source_version_id,
            work_id="work-wiring",
            source_ref=SourceRef(kind=SourceKind.MANUAL_URL, locator=url),
            canonical_url=url,
            retrieved_at=NOW,
            content_hash=f"sha256:{source_version_id}",
            access_policy=AccessPolicy.PERSIST,
        ),
        media_type="text/plain",
        text="chunk one\nchunk two",
        chunks=("chunk one", "chunk two"),
    )


def seed_run(tmp_path, run_id: str = "run-1", *, max_candidates: int = 7) -> SqliteResearchLibrary:
    plan = ResearchPlan(
        question="How do agents self-improve?",
        include_terms=("self-improving agents",),
        source_kinds=(SourceKind.MANUAL_URL,),
    )
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    library.save_project(ResearchProject("project-1", "Agent evolution"))
    library.save_run(
        ResearchRun(
            id=run_id,
            project_id="project-1",
            status=RunStatus.RUNNING,
            plan=plan,
            workflow_version="research-v1",
            created_at=NOW,
            updated_at=NOW,
        ),
        max_candidates=max_candidates,
    )
    return library


def overview_arguments(source_version_id: str, idempotency_key: str) -> dict:
    return {
        "idempotency_key": idempotency_key,
        "kind": "overview",
        "work_id": "work-wiring",
        "markdown": "Evidence-backed overview.",
        "structured": {
            "work_id": "work-wiring",
            "title": "Self improving agents",
            "conclusion": "The agent improves from feedback.",
            "relation": "Directly studies self-improvement.",
            "canonical_url": "https://example.org/paper",
            "tags": ["agent"],
            "scores": {
                "relevance": 5,
                "credibility": 4,
                "evidence_strength": 4,
                "novelty": 4,
                "timeliness": 4,
                "reproducibility": 3,
                "potential_value": 5,
            },
            "recommendation": "select",
        },
        "evidence_ids": [f"{source_version_id}#chunk-1"],
        "skill_name": "triage-sources",
        "skill_version": "1.0.0",
    }


def test_production_server_uses_run_spec_from_library(tmp_path) -> None:
    seed_run(tmp_path, max_candidates=7)

    server = build_production_server(make_env(tmp_path))
    context = server._context

    assert context.run_id == "run-1"
    assert context.plan.question == "How do agents self-improve?"
    assert context.plan.include_terms == ("self-improving agents",)
    assert context.plan.source_kinds == (SourceKind.MANUAL_URL,)
    assert context.max_candidates == 7
    assert context.allowed_tools == frozenset(TOOL_DEFINITIONS)


def test_artifacts_are_wrapped_in_policy_enforcer(tmp_path) -> None:
    seed_run(tmp_path)
    server = build_production_server(make_env(tmp_path))

    assert isinstance(server._context.artifacts, PolicyEnforcingArtifacts)


def test_materialized_source_persists_to_the_same_sqlite(tmp_path) -> None:
    seed_run(tmp_path)
    server = build_production_server(make_env(tmp_path))
    document = make_document("sv-persist-1", "https://example.org/paper")

    server._context.on_materialized(document)

    fresh = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    try:
        assert "sv-persist-1" in fresh.list_run_sources("run-1")
        chunks = fresh.read_chunks("sv-persist-1", start=1, limit=1)
        assert chunks[0].text == "chunk one"
    finally:
        fresh.close()


def test_restart_recovers_materialized_ids(tmp_path) -> None:
    seed_run(tmp_path)
    env = make_env(tmp_path)
    first = build_production_server(env)
    first._context.on_materialized(make_document("sv-restart-1", "https://example.org/restart"))

    restarted = build_production_server(env)
    result = call_ok(
        restarted,
        1,
        "read_source_chunks",
        {"source_version_id": "sv-restart-1", "start": 1, "limit": 2},
    )

    assert result["source_version_id"] == "sv-restart-1"
    assert [chunk["text"] for chunk in result["chunks"]] == ["chunk one", "chunk two"]


def test_cross_run_materialization_is_rejected(tmp_path) -> None:
    seed_run(tmp_path, run_id="run-a")
    seed_run(tmp_path, run_id="run-b")
    server_a = build_production_server(make_env(tmp_path, run_id="run-a"))
    server_a._context.on_materialized(make_document("sv-run-a", "https://example.org/run-a"))

    server_b = build_production_server(make_env(tmp_path, run_id="run-b"))
    read_result = call(server_b, 1, "read_source_chunks", {"source_version_id": "sv-run-a"})
    submit_result = call(server_b, 2, "submit_artifact", overview_arguments("sv-run-a", "xrun-1"))

    assert read_result["isError"] is True
    assert submit_result["isError"] is True


def test_submitted_artifact_is_listed_for_the_run(tmp_path) -> None:
    seed_run(tmp_path)
    server = build_production_server(make_env(tmp_path))
    server._context.on_materialized(make_document("sv-artifact-1", "https://example.org/artifact"))

    submitted = call_ok(server, 1, "submit_artifact", overview_arguments("sv-artifact-1", "ov-1"))

    assert submitted["artifact"]["version"] == 1
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    try:
        artifacts = library.list_artifacts("run-1")
        assert [artifact.id for artifact in artifacts] == [submitted["artifact"]["artifact_id"]]
    finally:
        library.close()


@pytest.mark.parametrize("variable", ALL_ENV_VARS)
def test_missing_environment_variable_raises_wiring_error(tmp_path, variable: str) -> None:
    env = make_env(tmp_path)
    del env[variable]

    with pytest.raises(WiringError) as excinfo:
        build_production_server(env)

    assert variable in str(excinfo.value)


@pytest.mark.parametrize("variable", ALL_ENV_VARS)
def test_empty_environment_variable_raises_wiring_error(tmp_path, variable: str) -> None:
    env = make_env(tmp_path)
    env[variable] = "  "

    with pytest.raises(WiringError) as excinfo:
        build_production_server(env)

    assert variable in str(excinfo.value)


def test_wrong_mode_raises_wiring_error_without_leaking_value(tmp_path) -> None:
    env = make_env(tmp_path)
    env[MODE_ENV] = "demo"

    with pytest.raises(WiringError) as excinfo:
        build_production_server(env)

    assert MODE_ENV in str(excinfo.value)
    assert "demo" not in str(excinfo.value)


def test_unknown_run_raises_wiring_error_without_fake_fallback(tmp_path) -> None:
    seed_run(tmp_path)
    env = make_env(tmp_path, run_id="run-missing")

    with pytest.raises(WiringError) as excinfo:
        build_production_server(env)

    assert "run-missing" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, KeyError)


def test_main_without_environment_fails_cleanly(monkeypatch, capsys) -> None:
    for variable in ALL_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)

    exit_code = main([])

    assert exit_code != 0
    captured = capsys.readouterr()
    assert RUN_ID_ENV in captured.err
    assert "Traceback" not in captured.err
