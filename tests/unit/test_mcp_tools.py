from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from autoresearch.adapters.fake import InMemoryArtifactStore, InMemorySourceAdapter
from autoresearch.adapters.library import InMemoryLibrarySearch
from autoresearch.adapters.mcp.server import ResearchToolsServer
from autoresearch.adapters.mcp.tools import (
    TOOL_DEFINITIONS,
    TOOL_HANDLERS,
    ToolContext,
    ToolError,
)
from autoresearch.domain import (
    ArtifactKind,
    Candidate,
    ErrorCategory,
    ResearchPlan,
    SourceDocument,
    SourceKind,
    SourceRef,
)
from autoresearch.ports.library import LibraryEntry


def make_plan() -> ResearchPlan:
    return ResearchPlan(
        question="Agent 如何自进化?",
        include_terms=("agent self-evolution",),
        source_kinds=(SourceKind.ARXIV, SourceKind.GITHUB, SourceKind.RSS),
    )


def make_context(**overrides: Any) -> ToolContext:
    document = InMemorySourceAdapter().materialize(
        SourceRef(kind=SourceKind.ARXIV, locator="arxiv:2401.00001")
    )
    defaults: dict[str, Any] = {
        "run_id": "run-test",
        "plan": make_plan(),
        "max_candidates": 2,
        "sources": InMemorySourceAdapter(),
        "artifacts": InMemoryArtifactStore(),
        "library": InMemoryLibrarySearch(
            entries=(
                LibraryEntry(
                    artifact_id="artifact-1",
                    run_id="run-old",
                    kind=ArtifactKind.OVERVIEW,
                    title="Agent Memory 综述",
                    summary="记忆机制概述",
                ),
            ),
            documents={document.source_version.id: document},
        ),
        "allowed_tools": frozenset(TOOL_DEFINITIONS),
        "allowed_domains": frozenset({"example.org"}),
        "materialized_ids": {document.source_version.id},
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


def valid_evidence(context: ToolContext) -> str:
    source_version_id = next(iter(context.materialized_ids))
    return f"{source_version_id}#chunk-0"


def call(context: ToolContext, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return TOOL_HANDLERS[tool](context, arguments)


class TestToolSchemas:
    @pytest.mark.parametrize("name", sorted(TOOL_DEFINITIONS))
    def test_input_schema_is_valid_json_schema(self, name: str) -> None:
        Draft202012Validator.check_schema(TOOL_DEFINITIONS[name]["inputSchema"])

    def test_submit_artifact_schema_has_no_run_id(self) -> None:
        schema = TOOL_DEFINITIONS["submit_artifact"]["inputSchema"]
        assert "run_id" not in schema["properties"]

    def test_submit_artifact_schema_enforces_required_fields(self) -> None:
        schema = TOOL_DEFINITIONS["submit_artifact"]["inputSchema"]
        valid = {
            "idempotency_key": "k1",
            "kind": "overview",
            "markdown": "# 内容",
            "evidence_ids": ["source-1#chunk-1"],
        }
        Draft202012Validator(schema).validate(valid)
        invalid = {"kind": "overview", "markdown": "# 内容", "evidence_ids": ["e"]}
        errors = list(Draft202012Validator(schema).iter_errors(invalid))
        assert errors


class TestDiscoverSources:
    def test_returns_candidates_within_budget(self) -> None:
        result = call(make_context(), "discover_sources", {})
        assert len(result["candidates"]) == 2  # clamped to max_candidates
        assert result["budget"] == 2
        assert {candidate["kind"] for candidate in result["candidates"]} <= {
            "arxiv",
            "github",
            "rss",
        }

    def test_limit_is_clamped_to_budget(self) -> None:
        result = call(make_context(), "discover_sources", {"limit": 50})
        assert len(result["candidates"]) == 2


class TestMaterializeSource:
    def test_materialize_returns_untrusted_envelope_and_registers_id(self) -> None:
        context = make_context()
        result = call(
            context, "materialize_source", {"locator": "arxiv:2401.00001", "kind": "arxiv"}
        )
        assert result["untrusted"] is True
        assert "不可信" in result["warning"]
        assert result["chunks"]
        assert result["source_version_id"] in context.materialized_ids

    def test_disallowed_domain_is_rejected(self) -> None:
        plan = ResearchPlan(
            question="q", include_terms=("t",), source_kinds=(SourceKind.MANUAL_URL,)
        )
        with pytest.raises(ToolError) as excinfo:
            call(
                make_context(plan=plan),
                "materialize_source",
                {"locator": "https://evil.example.net/paper"},
            )
        assert excinfo.value.failure.category is ErrorCategory.POLICY
        assert "allowlist" in excinfo.value.failure.message

    def test_allowed_domain_passes_validation(self) -> None:
        plan = ResearchPlan(
            question="q", include_terms=("t",), source_kinds=(SourceKind.MANUAL_URL,)
        )
        with pytest.raises(ToolError) as excinfo:
            call(
                make_context(plan=plan),
                "materialize_source",
                {"locator": "https://example.org/unknown"},
            )
        assert excinfo.value.failure.code == "mcp.unknown_source"
        assert excinfo.value.failure.category is ErrorCategory.PERMANENT

    def test_kind_outside_plan_is_rejected(self) -> None:
        plan = ResearchPlan(question="q", include_terms=("t",), source_kinds=(SourceKind.GITHUB,))
        context = make_context(plan=plan)
        with pytest.raises(ToolError) as excinfo:
            call(context, "materialize_source", {"locator": "arxiv:2401.00001", "kind": "arxiv"})
        assert excinfo.value.failure.category is ErrorCategory.POLICY

    def test_path_traversal_locator_is_rejected(self) -> None:
        with pytest.raises(ToolError) as excinfo:
            call(
                make_context(),
                "materialize_source",
                {"locator": "..\\..\\secrets.txt", "kind": "arxiv"},
            )
        assert excinfo.value.failure.category is ErrorCategory.POLICY


class TestSearchLibrary:
    def test_returns_summaries_without_full_text(self) -> None:
        result = call(make_context(), "search_library", {"query": "memory"})
        assert len(result["entries"]) == 1
        entry = result["entries"][0]
        assert entry["title"] == "Agent Memory 综述"
        assert "text" not in entry

    def test_empty_query_is_rejected(self) -> None:
        with pytest.raises(ToolError) as excinfo:
            call(make_context(), "search_library", {"query": "  "})
        assert excinfo.value.failure.code == "mcp.invalid_arguments"


class TestReadSourceChunks:
    def test_reads_chunks_of_materialized_source(self) -> None:
        context = make_context()
        document = context.sources.materialize(
            SourceRef(kind=SourceKind.ARXIV, locator="arxiv:2401.00001")
        )
        context.register_materialized(document.source_version.id)
        result = call(
            context, "read_source_chunks", {"source_version_id": document.source_version.id}
        )
        assert result["untrusted"] is True
        assert result["chunks"][0]["index"] == 0

    def test_unknown_or_foreign_source_is_rejected(self) -> None:
        with pytest.raises(ToolError) as excinfo:
            call(make_context(), "read_source_chunks", {"source_version_id": "source-other"})
        assert excinfo.value.failure.category is ErrorCategory.POLICY

    def test_path_traversal_id_is_rejected(self) -> None:
        for bad_id in ("../secrets", "..\\secrets", "a/b"):
            with pytest.raises(ToolError) as excinfo:
                call(make_context(), "read_source_chunks", {"source_version_id": bad_id})
            assert excinfo.value.failure.category is ErrorCategory.POLICY


class TestSubmitArtifact:
    def test_submit_writes_to_context_run(self) -> None:
        context = make_context()
        result = call(
            context,
            "submit_artifact",
            {
                "idempotency_key": "k1",
                "kind": "overview",
                "markdown": "# 概述",
                "evidence_ids": [valid_evidence(context)],
            },
        )
        assert result["idempotent_replay"] is False
        assert result["artifact"]["run_id"] == "run-test"
        assert result["artifact"]["version"] == 1

    def test_idempotent_replay_returns_same_artifact(self) -> None:
        context = make_context()
        arguments = {
            "idempotency_key": "k1",
            "kind": "overview",
            "markdown": "# 概述",
            "evidence_ids": [valid_evidence(context)],
        }
        first = call(context, "submit_artifact", arguments)
        second = call(context, "submit_artifact", arguments)
        assert second["idempotent_replay"] is True
        assert second["artifact"]["artifact_id"] == first["artifact"]["artifact_id"]
        assert len(context.artifacts.list("run-test")) == 1

    def test_missing_evidence_is_rejected(self) -> None:
        with pytest.raises(ToolError) as excinfo:
            call(
                make_context(),
                "submit_artifact",
                {
                    "idempotency_key": "k2",
                    "kind": "overview",
                    "markdown": "# 概述",
                    "evidence_ids": [],
                },
            )
        assert excinfo.value.failure.category is ErrorCategory.POLICY

    def test_forged_or_foreign_evidence_is_rejected(self) -> None:
        context = make_context()

        with pytest.raises(ToolError) as excinfo:
            call(
                context,
                "submit_artifact",
                {
                    "idempotency_key": "forged",
                    "kind": "overview",
                    "markdown": "# 概述",
                    "evidence_ids": ["source-foreign#chunk-0"],
                },
            )

        assert excinfo.value.failure.category is ErrorCategory.POLICY
        assert context.artifacts.list("run-test") == ()

    def test_unknown_kind_and_missing_key_are_rejected(self) -> None:
        with pytest.raises(ToolError):
            call(
                make_context(),
                "submit_artifact",
                {"idempotency_key": "k", "kind": "nope", "markdown": "x", "evidence_ids": ["e"]},
            )
        with pytest.raises(ToolError):
            call(
                make_context(),
                "submit_artifact",
                {"kind": "overview", "markdown": "x", "evidence_ids": ["e"]},
            )


class TestRequestHumanReview:
    def test_allowed_gate_notifies_callback(self) -> None:
        calls: list[tuple[str, str]] = []
        context = make_context(request_review=lambda gate, message: calls.append((gate, message)))
        result = call(context, "request_human_review", {"gate": "source_selection"})
        assert result == {"requested": True, "gate": "source_selection"}
        assert calls == [("source_selection", "")]

    def test_unknown_gate_is_rejected(self) -> None:
        with pytest.raises(ToolError) as excinfo:
            call(make_context(), "request_human_review", {"gate": "drop_database"})
        assert excinfo.value.failure.category is ErrorCategory.POLICY


class SlowSources:
    def discover(self, plan: ResearchPlan) -> Iterable[Candidate]:
        time.sleep(0.5)
        return ()

    def materialize(self, source_ref: SourceRef) -> SourceDocument:
        raise NotImplementedError


def test_tool_timeout_maps_to_transient_failure() -> None:
    context = make_context(sources=SlowSources())
    server = ResearchToolsServer(context, tool_timeout=0.05)
    line = (
        '{"jsonrpc":"2.0","id":1,"method":"tools/call",'
        '"params":{"name":"discover_sources","arguments":{}}}'
    )
    response = json.loads(server.handle_line(line) or "")
    result = response["result"]
    assert result["isError"] is True
    failure = json.loads(result["content"][0]["text"])["failure"]
    assert failure["category"] == "transient"
    assert failure["code"] == "mcp.tool_timeout"


def test_tool_hidden_from_run_cannot_be_called() -> None:
    context = make_context(allowed_tools=frozenset({"search_library"}))
    server = ResearchToolsServer(context)
    listed = json.loads(server.handle_line('{"jsonrpc":"2.0","id":1,"method":"tools/list"}') or "")
    assert [tool["name"] for tool in listed["result"]["tools"]] == ["search_library"]
    line = (
        '{"jsonrpc":"2.0","id":2,"method":"tools/call",'
        '"params":{"name":"submit_artifact","arguments":{}}}'
    )
    response = json.loads(server.handle_line(line) or "")
    assert response["result"]["isError"] is True
    failure = json.loads(response["result"]["content"][0]["text"])["failure"]
    assert failure["category"] == "policy"
    assert failure["code"] == "mcp.tool_not_available"
