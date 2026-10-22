from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_http import FakeTransport, ok

from autoresearch.adapters.sources.arxiv import API_URL, ArxivSource
from autoresearch.adapters.sources.http import HttpClient
from autoresearch.domain import AccessPolicy, AutoResearchError, ErrorCategory, ResearchPlan
from autoresearch.domain.models import SourceKind, SourceRef

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sources"
FIXED_NOW = datetime(2024, 3, 1, tzinfo=UTC)


def make_source(routes: dict) -> tuple[ArxivSource, FakeTransport]:
    transport = FakeTransport(routes)
    client = HttpClient(transport, requests_per_second=1000.0)
    return ArxivSource(client, clock=lambda: FIXED_NOW), transport


def make_plan(**kwargs: object) -> ResearchPlan:
    return ResearchPlan(question="q", include_terms=("agent self-evolution",), **kwargs)  # type: ignore[arg-type]


def test_discover_parses_atom_entries() -> None:
    source, transport = make_source({API_URL: ok((FIXTURES / "arxiv.xml").read_bytes())})
    candidates = list(source.discover(make_plan()))

    assert len(candidates) == 2
    first = candidates[0]
    assert first.source_ref.kind is SourceKind.ARXIV
    assert first.source_ref.locator == "arxiv:2401.00001"
    assert first.title == "Self-Refining Language Agents"
    assert first.canonical_url == "https://arxiv.org/abs/2401.00001v2"
    assert first.metadata["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert first.metadata["license"] == "http://creativecommons.org/licenses/by/4.0/"
    assert candidates[1].metadata["license"] is None
    assert "search_query=" in transport.requests[0].url
    assert "max_results=" in transport.requests[0].url


def test_materialize_maps_license_to_persist() -> None:
    source, _ = make_source(
        {f"{API_URL}?id_list=2401.00001": ok((FIXTURES / "arxiv_entry.xml").read_bytes())}
    )
    document = source.materialize(SourceRef(kind=SourceKind.ARXIV, locator="arxiv:2401.00001"))

    assert document.source_version.access_policy is AccessPolicy.PERSIST
    assert document.source_version.license == "http://creativecommons.org/licenses/by/4.0/"
    assert document.source_version.work_id == "2401.00001"
    assert "rewrites its policy" in document.text
    assert document.chunks == (document.text,)
    assert document.source_version.retrieved_at == FIXED_NOW


def test_materialize_without_license_is_metadata_only() -> None:
    body = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Memory</title>
    <summary>Feedback-driven memory consolidation.</summary>
    <published>2024-01-02T00:00:00Z</published>
  </entry>
</feed>
"""
    source, _ = make_source({f"{API_URL}?id_list=2401.00002": ok(body)})
    document = source.materialize(SourceRef(kind=SourceKind.ARXIV, locator="arxiv:2401.00002"))
    assert document.source_version.access_policy is AccessPolicy.METADATA_ONLY
    assert document.source_version.license is None


def test_materialize_unknown_id_is_permanent() -> None:
    empty_feed = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    source, _ = make_source({f"{API_URL}?id_list=nope": ok(empty_feed)})
    with pytest.raises(AutoResearchError) as excinfo:
        source.materialize(SourceRef(kind=SourceKind.ARXIV, locator="arxiv:nope"))
    assert excinfo.value.failure.code == "arxiv.unknown_id"
    assert excinfo.value.failure.category is ErrorCategory.PERMANENT


def test_invalid_xml_is_content_failure() -> None:
    source, _ = make_source({API_URL: ok(b"this is not xml")})
    with pytest.raises(AutoResearchError) as excinfo:
        list(source.discover(make_plan()))
    assert excinfo.value.failure.category is ErrorCategory.CONTENT
    assert excinfo.value.failure.code == "arxiv.parse_error"
