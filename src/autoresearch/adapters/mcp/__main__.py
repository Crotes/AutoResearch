"""Run the research-tools MCP server over stdio.

Started as `python -m autoresearch.adapters.mcp` by an MCP host (e.g. Pi).
The PoC wiring uses the in-memory adapters so the process is self-contained;
production wiring replaces the ports without touching the protocol layer.
"""

from __future__ import annotations

import sys

from autoresearch.adapters.fake import InMemoryArtifactStore, InMemorySourceAdapter
from autoresearch.adapters.library import InMemoryLibrarySearch
from autoresearch.adapters.mcp.server import ResearchToolsServer
from autoresearch.adapters.mcp.tools import TOOL_DEFINITIONS, ToolContext
from autoresearch.domain.models import ResearchPlan, SourceKind


def build_demo_server() -> ResearchToolsServer:
    plan = ResearchPlan(
        question="Agent 如何通过反馈实现自进化?",
        include_terms=("agent self-evolution", "智能体 自进化"),
        source_kinds=(SourceKind.ARXIV, SourceKind.GITHUB, SourceKind.RSS),
    )
    library = InMemoryLibrarySearch()
    context = ToolContext(
        run_id="run-mcp-stdio",
        plan=plan,
        max_candidates=20,
        sources=InMemorySourceAdapter(),
        artifacts=InMemoryArtifactStore(),
        library=library,
        allowed_tools=frozenset(TOOL_DEFINITIONS),
        on_materialized=library.register_document,
    )
    return ResearchToolsServer(context)


def _reconfigure_utf8(stream: object) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def main() -> int:
    _reconfigure_utf8(sys.stdin)
    _reconfigure_utf8(sys.stdout)
    build_demo_server().serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
