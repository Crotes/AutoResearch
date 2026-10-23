"""Run the research-tools MCP server over stdio.

Started as `python -m autoresearch.adapters.mcp` by an MCP host (e.g. Pi).
By default the process wires itself to the production run described by the
environment; `--demo` keeps the self-contained in-memory wiring.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from autoresearch.adapters.fake import InMemoryArtifactStore, InMemorySourceAdapter
from autoresearch.adapters.library import InMemoryLibrarySearch
from autoresearch.adapters.mcp.server import ResearchToolsServer
from autoresearch.adapters.mcp.tools import TOOL_DEFINITIONS, ToolContext
from autoresearch.adapters.mcp.wiring import WiringError, build_production_server
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


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="autoresearch.adapters.mcp",
        description="Serve the research-tools MCP server over stdio.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="use the self-contained in-memory demo wiring instead of the production environment",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    _reconfigure_utf8(sys.stdin)
    _reconfigure_utf8(sys.stdout)
    if args.demo:
        server = build_demo_server()
    else:
        try:
            server = build_production_server()
        except WiringError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    server.serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
