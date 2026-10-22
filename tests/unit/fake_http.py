"""Scripted HTTP transport and fake clocks for offline source tests."""

from __future__ import annotations

from autoresearch.adapters.sources.http import HttpRequest, HttpResponse


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class FakeSleeper:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.sleeps: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock.now += seconds


class FakeTransport:
    """Routes map a URL (exact or prefix) to responses; lists are consumed in
    order with the last item repeating."""

    def __init__(self, routes: dict[str, HttpResponse | Exception | list[object]]) -> None:
        self._routes = {
            key: (value if isinstance(value, list) else [value]) for key, value in routes.items()
        }
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest, timeout: float) -> HttpResponse:
        self.requests.append(request)
        queue = self._routes.get(request.url)
        if queue is None:
            matches = [v for k, v in self._routes.items() if request.url.startswith(k)]
            if not matches:
                raise AssertionError(f"no scripted route for {request.url}")
            queue = matches[0]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, HttpResponse)
        return item


def ok(body: bytes, *, content_type: str = "text/plain") -> HttpResponse:
    return HttpResponse(status=200, headers={"content-type": content_type}, body=body)


def status(code: int, *, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(status=code, headers=headers or {}, body=b"")
