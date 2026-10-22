"""Manual URL connector with strict access limits (SSRF-aware)."""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from autoresearch.adapters.sources.http import HttpClient
from autoresearch.adapters.sources.normalize import normalize_source_url
from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure
from autoresearch.domain.models import (
    AccessPolicy,
    Candidate,
    ResearchPlan,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
)

Clock = Callable[[], datetime]

_TEXTUAL_MAIN_TYPES = ("text/",)
_TEXTUAL_SUBTYPES = ("application/json", "application/xml", "application/xhtml+xml")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _failure(category: ErrorCategory, code: str, message: str) -> AutoResearchError:
    return AutoResearchError(Failure(category=category, code=code, message=message))


def is_internal_host(hostname: str) -> bool:
    host = hostname.lower().strip("[]")
    if host in {"localhost", "ip6-localhost"} or host.endswith(
        (".localhost", ".local", ".internal")
    ):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


class ManualUrlSource:
    """Fetch plan seed URLs; text-only, no internal addresses, metadata-only."""

    def __init__(self, http: HttpClient, *, clock: Clock = _utc_now) -> None:
        self._http = http
        self._clock = clock

    def discover(self, plan: ResearchPlan) -> Iterable[Candidate]:
        for url in plan.seed_urls:
            normalized = normalize_source_url(url)
            yield Candidate(
                source_ref=SourceRef(kind=SourceKind.MANUAL_URL, locator=normalized),
                title=normalized,
                canonical_url=normalized,
                metadata={"work_id": normalized},
            )

    def materialize(self, source_ref: SourceRef) -> SourceDocument:
        url = source_ref.locator
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise _failure(
                ErrorCategory.POLICY,
                "manual.unsupported_scheme",
                f"only http(s) URLs may be fetched: {url!r}",
            )
        hostname = parts.hostname or ""
        if is_internal_host(hostname):
            raise _failure(
                ErrorCategory.POLICY,
                "manual.internal_address",
                f"refusing to fetch internal address: {hostname!r}",
            )
        response = self._http.get(url)
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if not content_type.startswith(_TEXTUAL_MAIN_TYPES) and content_type not in (
            _TEXTUAL_SUBTYPES
        ):
            raise _failure(
                ErrorCategory.CONTENT,
                "manual.unsupported_media",
                f"unsupported content type {content_type!r} for {url!r}",
            )
        text = response.text()
        digest = hashlib.sha256(response.body).hexdigest()
        version = SourceVersion(
            id=f"manual-{digest[:12]}",
            work_id=normalize_source_url(url),
            source_ref=source_ref,
            canonical_url=normalize_source_url(url),
            retrieved_at=self._clock(),
            content_hash=digest,
            access_policy=AccessPolicy.METADATA_ONLY,
            license=None,
        )
        return SourceDocument(
            source_version=version, media_type=content_type, text=text, chunks=(text,)
        )
