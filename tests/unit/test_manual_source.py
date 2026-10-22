from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_http import FakeTransport, ok

from autoresearch.adapters.sources.http import HttpClient
from autoresearch.adapters.sources.manual import ManualUrlSource, is_internal_host
from autoresearch.domain import AccessPolicy, AutoResearchError, ErrorCategory, ResearchPlan
from autoresearch.domain.models import SourceKind, SourceRef

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sources"
PAGE_URL = "https://example.org/blog/adaptive-memory"
FIXED_NOW = datetime(2024, 3, 1, tzinfo=UTC)


def make_source(routes: dict) -> tuple[ManualUrlSource, FakeTransport]:
    transport = FakeTransport(routes)
    client = HttpClient(transport, requests_per_second=1000.0)
    return ManualUrlSource(client, clock=lambda: FIXED_NOW), transport


def test_discover_yields_seed_urls_normalized() -> None:
    source, transport = make_source({})
    plan = ResearchPlan(
        question="q",
        include_terms=("memory",),
        seed_urls=("https://Example.org/blog/adaptive-memory?utm_source=x",),
    )
    candidates = list(source.discover(plan))

    assert len(candidates) == 1
    assert candidates[0].source_ref.kind is SourceKind.MANUAL_URL
    assert candidates[0].source_ref.locator == PAGE_URL
    assert transport.requests == []


def test_materialize_text_page_is_metadata_only() -> None:
    page = ok((FIXTURES / "page.html").read_bytes(), content_type="text/html; charset=utf-8")
    source, _ = make_source({PAGE_URL: page})
    document = source.materialize(SourceRef(kind=SourceKind.MANUAL_URL, locator=PAGE_URL))

    assert document.source_version.access_policy is AccessPolicy.METADATA_ONLY
    assert document.media_type == "text/html"
    assert "Adaptive Memory" in document.text


def test_internal_addresses_are_rejected_before_fetch() -> None:
    source, transport = make_source({})
    for url in (
        "http://127.0.0.1/admin",
        "http://localhost:8080/",
        "http://192.168.1.1/router",
        "http://10.0.0.5/internal",
        "http://169.254.169.254/latest/meta-data",
        "http://printer.internal/",
    ):
        with pytest.raises(AutoResearchError) as excinfo:
            source.materialize(SourceRef(kind=SourceKind.MANUAL_URL, locator=url))
        assert excinfo.value.failure.category is ErrorCategory.POLICY
        assert excinfo.value.failure.code == "manual.internal_address"
    assert transport.requests == []


def test_non_http_scheme_is_rejected() -> None:
    source, _ = make_source({})
    with pytest.raises(AutoResearchError) as excinfo:
        source.materialize(SourceRef(kind=SourceKind.MANUAL_URL, locator="ftp://example.org/x"))
    assert excinfo.value.failure.code == "manual.unsupported_scheme"


def test_non_text_content_type_is_content_failure() -> None:
    source, _ = make_source({PAGE_URL: ok(b"%PDF-1.7", content_type="application/pdf")})
    with pytest.raises(AutoResearchError) as excinfo:
        source.materialize(SourceRef(kind=SourceKind.MANUAL_URL, locator=PAGE_URL))
    assert excinfo.value.failure.category is ErrorCategory.CONTENT
    assert excinfo.value.failure.code == "manual.unsupported_media"


def test_is_internal_host_classification() -> None:
    assert is_internal_host("localhost")
    assert is_internal_host("127.0.0.1")
    assert is_internal_host("::1")
    assert is_internal_host("example.org") is False
