from __future__ import annotations

import json
from datetime import UTC, datetime

from autoresearch.adapters import InMemorySourceAdapter, SqliteResearchLibrary
from autoresearch.adapters.mcp.server import ResearchToolsServer
from autoresearch.adapters.mcp.tools import ToolContext
from autoresearch.domain import ResearchPlan, ResearchProject, ResearchRun, RunStatus, SourceKind


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
    payload = json.loads(response)["result"]
    assert payload["isError"] is False, payload
    return json.loads(payload["content"][0]["text"])


def test_mcp_thread_pool_can_materialize_and_submit_to_sqlite(tmp_path) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    plan = ResearchPlan(
        question="How do agents self-improve?",
        include_terms=("self-improving agents",),
        source_kinds=(SourceKind.ARXIV,),
    )
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    library.save_project(ResearchProject("project-1", "Agent evolution"))
    library.save_run(
        ResearchRun(
            id="run-1",
            project_id="project-1",
            status=RunStatus.RUNNING,
            plan=plan,
            workflow_version="research-v1",
            created_at=now,
            updated_at=now,
        )
    )
    context = ToolContext(
        run_id="run-1",
        plan=plan,
        max_candidates=10,
        sources=InMemorySourceAdapter(clock=lambda: now),
        artifacts=library,
        library=library,
        allowed_tools=frozenset({"materialize_source", "submit_artifact"}),
        on_materialized=library.save_source,
    )
    server = ResearchToolsServer(context)

    materialized = call(
        server,
        1,
        "materialize_source",
        {"locator": "arxiv:2401.00001", "kind": "arxiv"},
    )
    submitted = call(
        server,
        2,
        "submit_artifact",
        {
            "idempotency_key": "overview-1",
            "kind": "overview",
            "work_id": "work-self-refine",
            "markdown": "Evidence-backed overview.",
            "structured": {
                "work_id": "work-self-refine",
                "title": "Self refining agents",
                "conclusion": "The agent improves from feedback.",
                "relation": "Directly studies self-improvement.",
                "canonical_url": "https://arxiv.org/abs/2401.00001",
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
            "evidence_ids": [f"{materialized['source_version_id']}#chunk-1"],
            "skill_name": "triage-sources",
            "skill_version": "1.0.0",
        },
    )

    assert submitted["artifact"]["version"] == 1
    assert library.search("refining")[0].work_id == "work-self-refine"
