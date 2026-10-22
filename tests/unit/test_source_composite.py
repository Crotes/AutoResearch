from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_http import FakeTransport, ok, status

from autoresearch.adapters.sources.arxiv import API_URL as ARXIV_API
from autoresearch.adapters.sources.arxiv import ArxivSource
from autoresearch.adapters.sources.composite import CompositeSourceAdapter
from autoresearch.adapters.sources.github import API_URL as GITHUB_API
from autoresearch.adapters.sources.github import GitHubSource
from autoresearch.adapters.sources.http import HttpClient
from autoresearch.adapters.sources.manual import ManualUrlSource
from autoresearch.adapters.sources.rss import RssSource
from autoresearch.domain import AutoResearchError, ErrorCategory, ResearchPlan
from autoresearch.domain.models import (
    Candidate,
    SourceDocument,
    SourceKind,
    SourceRef,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sources"
FEED_URL = "https://example.org/feed.xml"
SEED_URL = "https://example.org/blog/adaptive-memory"
FIXED_NOW = datetime(2024, 3, 1, tzinfo=UTC)


def make_composite(routes: dict) -> CompositeSourceAdapter:
    transport = FakeTransport(routes)
    client = HttpClient(transport, requests_per_second=1000.0)
    return CompositeSourceAdapter(
        {
            SourceKind.ARXIV: ArxivSource(client, clock=lambda: FIXED_NOW),
            SourceKind.GITHUB: GitHubSource(client, token="", clock=lambda: FIXED_NOW),
            SourceKind.RSS: RssSource(client, allowed_feeds=(FEED_URL,), clock=lambda: FIXED_NOW),
            SourceKind.MANUAL_URL: ManualUrlSource(client, clock=lambda: FIXED_NOW),
        }
    )


def all_routes() -> dict:
    return {
        ARXIV_API: ok((FIXTURES / "arxiv.xml").read_bytes()),
        f"{GITHUB_API}/search/repositories": ok((FIXTURES / "github_search.json").read_bytes()),
        FEED_URL: ok((FIXTURES / "feed.xml").read_bytes()),
    }


def make_plan() -> ResearchPlan:
    return ResearchPlan(
        question="q",
        include_terms=("agent self-evolution",),
        source_kinds=(
            SourceKind.ARXIV,
            SourceKind.GITHUB,
            SourceKind.RSS,
            SourceKind.MANUAL_URL,
        ),
        seed_urls=(SEED_URL,),
    )


def test_four_kinds_produce_uniform_candidates() -> None:
    composite = make_composite(all_routes())
    candidates, failures = composite.discover_with_failures(make_plan())

    assert failures == ()
    kinds = {candidate.source_ref.kind for candidate in candidates}
    assert kinds == {SourceKind.ARXIV, SourceKind.GITHUB, SourceKind.RSS, SourceKind.MANUAL_URL}
    for candidate in candidates:
        assert isinstance(candidate, Candidate)
        assert isinstance(candidate.source_ref, SourceRef)
        assert candidate.source_ref.locator
        assert candidate.canonical_url
        assert candidate.metadata["work_id"]


def test_single_source_failure_is_isolated() -> None:
    routes = all_routes()
    routes[f"{GITHUB_API}/search/repositories"] = status(500)
    composite = make_composite(routes)

    candidates, failures = composite.discover_with_failures(make_plan())

    kinds = {candidate.source_ref.kind for candidate in candidates}
    assert SourceKind.GITHUB not in kinds
    assert {SourceKind.ARXIV, SourceKind.RSS, SourceKind.MANUAL_URL} <= kinds
    assert len(failures) == 1
    assert failures[0].category is ErrorCategory.TRANSIENT
    assert failures[0].should_retry
    assert failures[0].details["source_kind"] == "github"

    # the port-facing discover() keeps the failures quiet
    assert list(composite.discover(make_plan()))


def test_permanent_failure_is_distinguishable_from_transient() -> None:
    routes = all_routes()
    routes[f"{GITHUB_API}/search/repositories"] = status(404)
    composite = make_composite(routes)

    _, failures = composite.discover_with_failures(make_plan())

    assert len(failures) == 1
    assert failures[0].category is ErrorCategory.PERMANENT
    assert not failures[0].should_retry


def test_unexpected_exception_becomes_internal_failure() -> None:
    class BrokenSource:
        def discover(self, plan: ResearchPlan) -> list[Candidate]:
            raise RuntimeError("boom")

        def materialize(self, source_ref: SourceRef) -> SourceDocument:
            raise NotImplementedError

    composite = CompositeSourceAdapter(
        {
            SourceKind.ARXIV: BrokenSource(),
            SourceKind.RSS: RssSource(
                HttpClient(FakeTransport({FEED_URL: ok((FIXTURES / "feed.xml").read_bytes())})),
                allowed_feeds=(FEED_URL,),
            ),
        }
    )
    candidates, failures = composite.discover_with_failures(
        ResearchPlan(
            question="q",
            include_terms=("t",),
            source_kinds=(SourceKind.ARXIV, SourceKind.RSS),
        )
    )
    assert len(candidates) == 2
    assert len(failures) == 1
    assert failures[0].category is ErrorCategory.INTERNAL


def test_unconfigured_kind_is_a_permanent_failure() -> None:
    composite = CompositeSourceAdapter({})
    candidates, failures = composite.discover_with_failures(
        ResearchPlan(question="q", include_terms=("t",), source_kinds=(SourceKind.ARXIV,))
    )
    assert candidates == ()
    assert failures[0].code == "sources.kind_not_configured"

    with pytest.raises(AutoResearchError) as excinfo:
        composite.materialize(SourceRef(kind=SourceKind.ARXIV, locator="arxiv:2401.00001"))
    assert excinfo.value.failure.code == "sources.kind_not_configured"


def test_materialize_dispatches_by_kind() -> None:
    routes = {f"{ARXIV_API}?id_list=2401.00001": ok((FIXTURES / "arxiv_entry.xml").read_bytes())}
    composite = make_composite(routes)
    document = composite.materialize(SourceRef(kind=SourceKind.ARXIV, locator="arxiv:2401.00001"))
    assert document.source_version.work_id == "2401.00001"
