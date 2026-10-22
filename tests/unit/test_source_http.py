from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest
from fake_http import FakeClock, FakeSleeper, FakeTransport, ok, status

from autoresearch.adapters.sources.http import FileCache, HttpClient, HttpRequest
from autoresearch.domain import AutoResearchError, ErrorCategory, Failure


def make_client(
    transport: FakeTransport,
    *,
    clock: FakeClock | None = None,
    sleeper: FakeSleeper | None = None,
    **kwargs: object,
) -> tuple[HttpClient, FakeClock, FakeSleeper]:
    fake_clock = clock or FakeClock()
    fake_sleeper = sleeper or FakeSleeper(fake_clock)
    client = HttpClient(
        transport,
        clock=fake_clock,
        wall_clock=fake_clock,
        sleeper=fake_sleeper,
        base_delay=0.5,
        **kwargs,  # type: ignore[arg-type]
    )
    return client, fake_clock, fake_sleeper


def test_success_passthrough() -> None:
    transport = FakeTransport({"https://example.org/": ok(b"hello")})
    client, _, _ = make_client(transport)
    response = client.get("https://example.org/")
    assert response.status == 200
    assert response.text() == "hello"


def test_404_is_permanent_and_not_retried() -> None:
    transport = FakeTransport({"https://example.org/x": status(404)})
    client, _, _ = make_client(transport)
    with pytest.raises(AutoResearchError) as excinfo:
        client.get("https://example.org/x")
    assert excinfo.value.failure.category is ErrorCategory.PERMANENT
    assert excinfo.value.failure.code == "http.not_found"
    assert len(transport.requests) == 1


def test_401_is_policy_and_not_retried() -> None:
    transport = FakeTransport({"https://example.org/x": status(401)})
    client, _, _ = make_client(transport)
    with pytest.raises(AutoResearchError) as excinfo:
        client.get("https://example.org/x")
    assert excinfo.value.failure.category is ErrorCategory.POLICY
    assert len(transport.requests) == 1


def test_429_retries_and_honors_retry_after() -> None:
    transport = FakeTransport(
        {"https://example.org/x": [status(429, headers={"retry-after": "2"}), ok(b"done")]}
    )
    client, _, sleeper = make_client(transport)
    response = client.get("https://example.org/x")
    assert response.status == 200
    assert sleeper.sleeps == [2.0]
    assert len(transport.requests) == 2


def test_429_exhaustion_is_transient_and_distinguishable() -> None:
    transport = FakeTransport({"https://example.org/x": status(429)})
    client, _, sleeper = make_client(transport, max_retries=3)
    with pytest.raises(AutoResearchError) as excinfo:
        client.get("https://example.org/x")
    failure = excinfo.value.failure
    assert failure.category is ErrorCategory.TRANSIENT
    assert failure.code == "http.retries_exhausted"
    assert failure.should_retry
    assert len(transport.requests) == 4
    assert sleeper.sleeps == [0.5, 1.0, 2.0]


def test_500_is_transient_and_retried() -> None:
    transport = FakeTransport({"https://example.org/x": [status(500), ok(b"ok")]})
    client, _, _ = make_client(transport)
    assert client.get("https://example.org/x").status == 200


def test_network_error_is_transient_and_retried() -> None:
    transport = FakeTransport(
        {
            "https://example.org/x": [
                urllib.error.URLError("connection reset"),
                ok(b"recovered"),
            ]
        }
    )
    client, _, _ = make_client(transport)
    assert client.get("https://example.org/x").status == 200


def test_network_error_exhaustion() -> None:
    transport = FakeTransport({"https://example.org/x": urllib.error.URLError("down")})
    client, _, _ = make_client(transport, max_retries=1)
    with pytest.raises(AutoResearchError) as excinfo:
        client.get("https://example.org/x")
    assert excinfo.value.failure.category is ErrorCategory.TRANSIENT


def test_per_host_token_bucket_rate_limits() -> None:
    transport = FakeTransport({"https://example.org/": ok(b"a"), "https://other.org/": ok(b"b")})
    client, _, sleeper = make_client(transport, requests_per_second=2.0)
    client.get("https://example.org/1")
    client.get("https://example.org/2")
    client.get("https://other.org/1")  # different host: no wait
    assert sleeper.sleeps == []
    client.get("https://example.org/3")
    assert sleeper.sleeps == [0.5]


def test_cache_hit_serves_offline_and_expires(tmp_path: Path) -> None:
    transport = FakeTransport({"https://example.org/x": ok(b"cached")})
    clock = FakeClock(start=1000.0)
    sleeper = FakeSleeper(clock)
    cache = FileCache(tmp_path / "cache", ttl=60.0)
    client = HttpClient(transport, cache=cache, clock=clock, wall_clock=clock, sleeper=sleeper)
    assert client.get("https://example.org/x").text() == "cached"
    clock.now += 30
    assert client.get("https://example.org/x").text() == "cached"
    assert len(transport.requests) == 1
    clock.now += 31  # beyond ttl
    assert client.get("https://example.org/x").text() == "cached"
    assert len(transport.requests) == 2


def test_sensitive_response_can_bypass_file_cache(tmp_path: Path) -> None:
    transport = FakeTransport({"https://example.org/private": ok(b"private body")})
    cache = FileCache(tmp_path / "cache")
    client, _, _ = make_client(transport, cache=cache)

    assert client.get("https://example.org/private", cache_response=False).status == 200

    assert not (tmp_path / "cache").exists()


def test_redirect_target_is_revalidated_before_following() -> None:
    start = "https://example.org/start"
    private = "http://127.0.0.1/admin"
    transport = FakeTransport(
        {
            start: status(302, headers={"location": private}),
            private: ok(b"secret"),
        }
    )
    client, _, _ = make_client(transport)

    def validate(url: str) -> None:
        if "127.0.0.1" in url:
            raise AutoResearchError(
                Failure(
                    category=ErrorCategory.POLICY,
                    code="test.private_redirect",
                    message="private redirect",
                )
            )

    with pytest.raises(AutoResearchError) as excinfo:
        client.get(start, url_validator=validate)

    assert excinfo.value.failure.category is ErrorCategory.POLICY
    assert [request.url for request in transport.requests] == [start]


def test_request_headers_are_passed_to_transport() -> None:
    transport = FakeTransport({"https://example.org/": ok(b"")})
    client, _, _ = make_client(transport)
    client.get("https://example.org/", headers={"Authorization": "Bearer t"})
    request = transport.requests[0]
    assert isinstance(request, HttpRequest)
    assert request.headers == {"Authorization": "Bearer t"}
