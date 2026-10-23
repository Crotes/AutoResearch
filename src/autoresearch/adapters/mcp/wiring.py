"""Production wiring for the research-tools MCP server.

Composition root for real runs: reads its configuration from the environment,
opens the SQLite-backed research library, and builds a
:class:`ResearchToolsServer` whose tools are scoped to exactly one run.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from autoresearch.adapters import SqliteResearchLibrary
from autoresearch.adapters.mcp.server import ResearchToolsServer
from autoresearch.adapters.mcp.tools import TOOL_DEFINITIONS, ToolContext
from autoresearch.adapters.sources import (
    ArxivSource,
    CompositeSourceAdapter,
    FileCache,
    GitHubSource,
    HttpClient,
    ManualUrlSource,
    RssSource,
)
from autoresearch.application.artifact_policy import PolicyEnforcingArtifacts
from autoresearch.domain.models import SourceDocument, SourceKind

RUN_ID_ENV = "AUTORESEARCH_RUN_ID"
DATABASE_ENV = "AUTORESEARCH_DATABASE"
CONTENT_ROOT_ENV = "AUTORESEARCH_CONTENT_ROOT"
MODE_ENV = "AUTORESEARCH_MODE"

RUN_MODE = "run"
REQUIRED_ENV_VARS = (RUN_ID_ENV, DATABASE_ENV, CONTENT_ROOT_ENV, MODE_ENV)


class WiringError(Exception):
    """Raised when the production server cannot be wired from the environment."""


def _require_env(environ: Mapping[str, str]) -> dict[str, str]:
    values = {name: environ.get(name, "").strip() for name in REQUIRED_ENV_VARS}
    missing = [name for name in REQUIRED_ENV_VARS if not values[name]]
    if missing:
        raise WiringError(f"missing required environment variables: {', '.join(missing)}")
    return values


def build_production_server(environ: Mapping[str, str] | None = None) -> ResearchToolsServer:
    """Build a run-scoped server from the environment; never falls back to fakes."""
    if environ is None:
        environ = os.environ
    values = _require_env(environ)
    if values[MODE_ENV] != RUN_MODE:
        raise WiringError(f"{MODE_ENV} must be {RUN_MODE!r} for production wiring")
    run_id = values[RUN_ID_ENV]
    content_root = Path(values[CONTENT_ROOT_ENV])
    library = SqliteResearchLibrary(values[DATABASE_ENV], content_root)
    try:
        library.get_run(run_id)
        spec = library.get_run_spec(run_id)
    except KeyError as error:
        library.close()
        raise WiringError(f"run {run_id!r} was not found in the research library") from error

    client = HttpClient(cache=FileCache(content_root.parent / "cache"))
    sources = CompositeSourceAdapter(
        {
            SourceKind.ARXIV: ArxivSource(client),
            SourceKind.GITHUB: GitHubSource(client),
            SourceKind.RSS: RssSource(client, allowed_feeds=spec.plan.seed_urls),
            SourceKind.MANUAL_URL: ManualUrlSource(client),
        }
    )

    materialized_ids = set(library.list_run_sources(run_id))

    def persist_materialized(document: SourceDocument) -> None:
        stored_id = library.save_source(document)
        library.save_run_source(run_id, stored_id)
        materialized_ids.add(document.source_version.id)
        materialized_ids.add(stored_id)

    context = ToolContext(
        run_id=run_id,
        plan=spec.plan,
        max_candidates=spec.max_candidates,
        sources=sources,
        artifacts=PolicyEnforcingArtifacts(library),
        library=library,
        allowed_tools=frozenset(TOOL_DEFINITIONS),
        materialized_ids=materialized_ids,
        on_materialized=persist_materialized,
    )
    return ResearchToolsServer(context)
