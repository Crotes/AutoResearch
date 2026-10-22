from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fake_http import FakeTransport, ok, status

from autoresearch.adapters.sources.github import API_URL, GitHubSource
from autoresearch.adapters.sources.http import HttpClient
from autoresearch.domain import AccessPolicy, ResearchPlan
from autoresearch.domain.models import SourceKind, SourceRef

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sources"
FIXED_NOW = datetime(2024, 3, 1, tzinfo=UTC)


def make_source(
    routes: dict, *, token: str | None = "", per_page: int = 30
) -> tuple[GitHubSource, FakeTransport]:
    transport = FakeTransport(routes)
    client = HttpClient(transport, requests_per_second=1000.0)
    return GitHubSource(client, token=token, clock=lambda: FIXED_NOW, per_page=per_page), transport


def make_plan() -> ResearchPlan:
    return ResearchPlan(question="q", include_terms=("agent self-evolution",))


def test_discover_parses_search_results() -> None:
    source, transport = make_source(
        {f"{API_URL}/search/repositories": ok((FIXTURES / "github_search.json").read_bytes())}
    )
    candidates = list(source.discover(make_plan()))

    assert len(candidates) == 2
    first = candidates[0]
    assert first.source_ref.kind is SourceKind.GITHUB
    assert first.source_ref.locator == "github:lab/evolving-agent"
    assert first.canonical_url == "https://github.com/lab/evolving-agent"
    assert first.metadata["stars"] == 512
    assert first.metadata["license"] == "Apache-2.0"
    assert candidates[1].metadata["license"] is None
    assert "q=" in transport.requests[0].url


def test_discover_follows_search_pages() -> None:
    first = b'{"items":[{"full_name":"lab/one","html_url":"https://github.com/lab/one"}]}'
    second = b'{"items":[{"full_name":"lab/two","html_url":"https://github.com/lab/two"}]}'
    empty = b'{"items":[]}'
    source, transport = make_source(
        {f"{API_URL}/search/repositories": [ok(first), ok(second), ok(empty)]},
        per_page=1,
    )

    candidates = list(source.discover(make_plan()))

    assert [candidate.title for candidate in candidates] == ["lab/one", "lab/two"]
    assert len(transport.requests) == 3
    assert "page=2" in transport.requests[1].url


def test_token_adds_authorization_header() -> None:
    source, transport = make_source(
        {f"{API_URL}/search/repositories": ok(b'{"items": []}')}, token="secret-token"
    )
    list(source.discover(make_plan()))
    assert transport.requests[0].headers["Authorization"] == "Bearer secret-token"


def test_no_token_sends_no_authorization(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    source, transport = make_source(
        {f"{API_URL}/search/repositories": ok(b'{"items": []}')}, token=None
    )
    list(source.discover(make_plan()))
    assert "Authorization" not in transport.requests[0].headers


def test_materialize_combines_metadata_readme_and_release() -> None:
    routes = {
        f"{API_URL}/repos/lab/evolving-agent": ok((FIXTURES / "github_repo.json").read_bytes()),
        f"{API_URL}/repos/lab/evolving-agent/readme": ok(
            (FIXTURES / "github_readme.json").read_bytes()
        ),
        f"{API_URL}/repos/lab/evolving-agent/releases/latest": ok(
            (FIXTURES / "github_release.json").read_bytes()
        ),
    }
    source, _ = make_source(routes)
    document = source.materialize(
        SourceRef(kind=SourceKind.GITHUB, locator="github:lab/evolving-agent")
    )

    assert "Evolving Agent Toolkit" in document.text
    assert "v1.2.0" in document.text
    assert document.source_version.access_policy is AccessPolicy.PERSIST
    assert document.source_version.license == "Apache-2.0"
    assert len(document.chunks) >= 3


def test_materialize_without_release_or_license() -> None:
    routes = {
        f"{API_URL}/repos/lab/reflexion-notes": ok(
            b'{"full_name": "lab/reflexion-notes", "description": "Notes.", "license": null}'
        ),
        f"{API_URL}/repos/lab/reflexion-notes/readme": status(404),
        f"{API_URL}/repos/lab/reflexion-notes/releases/latest": status(404),
    }
    source, transport = make_source(routes)
    document = source.materialize(
        SourceRef(kind=SourceKind.GITHUB, locator="github:lab/reflexion-notes")
    )
    assert document.text == ""
    assert document.chunks == ()
    assert document.source_version.access_policy is AccessPolicy.METADATA_ONLY
    assert document.source_version.license is None
    assert len(transport.requests) == 1
