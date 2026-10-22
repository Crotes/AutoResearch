from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_http import FakeTransport, ok

from autoresearch.adapters.sources.http import HttpClient
from autoresearch.adapters.sources.rss import RssSource
from autoresearch.domain import AccessPolicy, AutoResearchError, ErrorCategory, ResearchPlan
from autoresearch.domain.models import SourceKind, SourceRef

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sources"
FEED_URL = "https://example.org/feed.xml"
FIXED_NOW = datetime(2024, 3, 1, tzinfo=UTC)


def make_source(
    routes: dict, *, allowed: tuple[str, ...] = (FEED_URL,)
) -> tuple[RssSource, FakeTransport]:
    transport = FakeTransport(routes)
    client = HttpClient(transport, requests_per_second=1000.0)
    return RssSource(client, allowed_feeds=allowed, clock=lambda: FIXED_NOW), transport


def make_plan() -> ResearchPlan:
    return ResearchPlan(question="q", include_terms=("memory",))


def feed_routes() -> dict:
    return {FEED_URL: ok((FIXTURES / "feed.xml").read_bytes())}


def test_discover_parses_allowlisted_feed() -> None:
    source, _ = make_source(feed_routes())
    candidates = list(source.discover(make_plan()))

    assert len(candidates) == 2
    first = candidates[0]
    assert first.source_ref.kind is SourceKind.RSS
    assert first.source_ref.locator == f"{FEED_URL}#urn:uuid:adaptive-memory"
    assert first.title == "Adaptive Memory for Long-Lived Agents"
    # tracking params are stripped from the canonical URL
    assert first.canonical_url == "https://example.org/blog/adaptive-memory"


def test_empty_allowlist_discovers_nothing() -> None:
    source, transport = make_source(feed_routes(), allowed=())
    assert list(source.discover(make_plan())) == []
    assert transport.requests == []


def test_materialize_returns_metadata_only_document() -> None:
    source, _ = make_source(feed_routes())
    ref = SourceRef(kind=SourceKind.RSS, locator=f"{FEED_URL}#urn:uuid:adaptive-memory")
    document = source.materialize(ref)

    assert document.source_version.access_policy is AccessPolicy.METADATA_ONLY
    assert document.text == "Pruning and consolidating memories using task feedback."
    assert document.source_version.retrieved_at == FIXED_NOW


def test_materialize_rejects_feed_outside_allowlist() -> None:
    source, transport = make_source(feed_routes())
    ref = SourceRef(kind=SourceKind.RSS, locator="https://evil.example.net/f#item-1")
    with pytest.raises(AutoResearchError) as excinfo:
        source.materialize(ref)
    assert excinfo.value.failure.category is ErrorCategory.POLICY
    assert excinfo.value.failure.code == "rss.feed_not_allowed"
    assert transport.requests == []  # rejected before any fetch


def test_materialize_unknown_item_is_permanent() -> None:
    source, _ = make_source(feed_routes())
    ref = SourceRef(kind=SourceKind.RSS, locator=f"{FEED_URL}#urn:uuid:missing")
    with pytest.raises(AutoResearchError) as excinfo:
        source.materialize(ref)
    assert excinfo.value.failure.code == "rss.unknown_item"
    assert excinfo.value.failure.category is ErrorCategory.PERMANENT


def test_invalid_feed_xml_is_content_failure() -> None:
    source, _ = make_source({FEED_URL: ok(b"not xml")})
    with pytest.raises(AutoResearchError) as excinfo:
        list(source.discover(make_plan()))
    assert excinfo.value.failure.category is ErrorCategory.CONTENT
