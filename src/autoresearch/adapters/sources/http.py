"""Minimal HTTP client with injectable transport, retries, and rate limiting.

Production uses ``urllib``; tests inject a scripted transport plus fake clocks
so retry/backoff/rate-limit behaviour is exercised fully offline.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 0.5
DEFAULT_REQUESTS_PER_SECOND = 5.0
DEFAULT_CACHE_TTL = 24 * 3600.0
DEFAULT_MAX_REDIRECTS = 5

USER_AGENT = "autoresearch-poc/0.1 (+https://autoresearch.local)"


@dataclass(frozen=True, slots=True)
class HttpRequest:
    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


Transport = Callable[[HttpRequest, float], HttpResponse]
MonotonicClock = Callable[[], float]
Sleeper = Callable[[float], None]
UrlValidator = Callable[[str], None]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[no-untyped-def]
        self, req, fp, code, msg, headers, newurl
    ):
        return None


def urllib_transport(request: HttpRequest, timeout: float) -> HttpResponse:
    headers = {"User-Agent": USER_AGENT, **request.headers}
    urllib_request = urllib.request.Request(request.url, headers=headers)
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(urllib_request, timeout=timeout) as response:
            return HttpResponse(
                status=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.read(),
            )
    except urllib.error.HTTPError as error:
        return HttpResponse(
            status=error.code,
            headers={key.lower(): value for key, value in error.headers.items()},
            body=error.read(),
        )


def classify_status(status: int) -> Failure | None:
    """Map an HTTP status onto a Failure; None means success."""
    if 200 <= status < 300:
        return None
    if status == 429 or status >= 500:
        return Failure(
            category=ErrorCategory.TRANSIENT,
            code="http.retryable_status",
            message=f"http status {status} is retryable",
            details={"status": status},
        )
    if status in (401, 403):
        return Failure(
            category=ErrorCategory.POLICY,
            code="http.forbidden",
            message=f"http status {status} forbids access",
            details={"status": status},
        )
    if status in (404, 410):
        return Failure(
            category=ErrorCategory.PERMANENT,
            code="http.not_found",
            message=f"http status {status}: resource is gone",
            details={"status": status},
        )
    return Failure(
        category=ErrorCategory.PERMANENT,
        code="http.unexpected_status",
        message=f"unexpected http status {status}",
        details={"status": status},
    )


class _TokenBucket:
    def __init__(self, rate: float) -> None:
        self.rate = rate
        self.capacity = max(rate, 1.0)
        self.tokens = self.capacity
        self.updated = 0.0

    def acquire(self, clock: MonotonicClock, sleeper: Sleeper) -> None:
        while True:
            now = clock()
            self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            sleeper((1.0 - self.tokens) / self.rate)


class FileCache:
    """Body+meta file cache keyed by sha256(url); TTL in seconds."""

    def __init__(self, root: Path, ttl: float = DEFAULT_CACHE_TTL) -> None:
        self._root = root
        self._ttl = ttl

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._root / f"{key}.body", self._root / f"{key}.json"

    def get(self, url: str, now: float) -> HttpResponse | None:
        body_path, meta_path = self._paths(url)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if now - float(meta["fetched_at"]) > self._ttl:
                return None
            return HttpResponse(
                status=int(meta["status"]),
                headers={str(k): str(v) for k, v in meta["headers"].items()},
                body=body_path.read_bytes(),
            )
        except (OSError, ValueError, KeyError):
            return None

    def put(self, url: str, response: HttpResponse, now: float) -> None:
        body_path, meta_path = self._paths(url)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(response.body)
            meta_path.write_text(
                json.dumps(
                    {
                        "fetched_at": now,
                        "status": response.status,
                        "headers": response.headers,
                        "url": url,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass


class HttpClient:
    def __init__(
        self,
        transport: Transport | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        cache: FileCache | None = None,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        clock: MonotonicClock = time.monotonic,
        wall_clock: MonotonicClock = time.time,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self._transport = transport or urllib_transport
        self._timeout = timeout
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._requests_per_second = requests_per_second
        self._cache = cache
        self._max_redirects = max_redirects
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleeper = sleeper
        self._buckets: dict[str, _TokenBucket] = {}

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        cache_response: bool = True,
        url_validator: UrlValidator | None = None,
    ) -> HttpResponse:
        if url_validator is not None:
            url_validator(url)
        if cache_response and self._cache is not None:
            cached = self._cache.get(url, self._wall_clock())
            if cached is not None:
                return cached
        current_url = url
        for redirect_count in range(self._max_redirects + 1):
            response = self._fetch(current_url, headers or {})
            if response.status not in _REDIRECT_STATUSES:
                if cache_response and self._cache is not None:
                    self._cache.put(url, response, self._wall_clock())
                return response
            location = response.headers.get("location")
            if not location:
                raise AutoResearchError(
                    Failure(
                        category=ErrorCategory.PERMANENT,
                        code="http.redirect_without_location",
                        message=f"http redirect from {current_url!r} has no location",
                    )
                )
            if redirect_count >= self._max_redirects:
                raise AutoResearchError(
                    Failure(
                        category=ErrorCategory.PERMANENT,
                        code="http.too_many_redirects",
                        message=f"too many redirects while fetching {url!r}",
                    )
                )
            current_url = urljoin(current_url, location)
            if url_validator is not None:
                url_validator(current_url)
        raise AssertionError("redirect loop must return or raise")

    def _fetch(self, url: str, headers: dict[str, str]) -> HttpResponse:
        request = HttpRequest(url=url, headers=headers)
        last_failure: Failure | None = None
        for attempt in range(self._max_retries + 1):
            self._bucket_for(url).acquire(self._clock, self._sleeper)
            try:
                response = self._transport(request, self._timeout)
            except (urllib.error.URLError, OSError, TimeoutError) as error:
                last_failure = Failure(
                    category=ErrorCategory.TRANSIENT,
                    code="http.network_error",
                    message=f"network error: {error}",
                    retryable=True,
                )
                if attempt < self._max_retries:
                    self._sleeper(self._base_delay * (2.0**attempt))
                continue
            if response.status in _REDIRECT_STATUSES:
                return response
            failure = classify_status(response.status)
            if failure is None:
                return response
            if failure.category is not ErrorCategory.TRANSIENT:
                raise AutoResearchError(failure)
            last_failure = failure
            if attempt < self._max_retries:
                self._sleeper(self._retry_delay(response, attempt))
        assert last_failure is not None
        raise AutoResearchError(
            Failure(
                category=last_failure.category,
                code="http.retries_exhausted",
                message=f"{last_failure.message}; exhausted {self._max_retries} retries",
                details=dict(last_failure.details),
            )
        )

    def _retry_delay(self, response: HttpResponse, attempt: int) -> float:
        retry_after = response.headers.get("retry-after", "")
        try:
            parsed = float(retry_after)
        except ValueError:
            return self._base_delay * (2.0**attempt)
        return max(parsed, 0.0)

    def _bucket_for(self, url: str) -> _TokenBucket:
        host = urlsplit(url).hostname or url
        bucket = self._buckets.get(host)
        if bucket is None:
            bucket = _TokenBucket(self._requests_per_second)
            self._buckets[host] = bucket
        return bucket
