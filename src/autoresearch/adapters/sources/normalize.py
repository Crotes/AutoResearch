"""URL normalization and license-to-access-policy mapping shared by connectors."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from autoresearch.domain.models import AccessPolicy

TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "igshid",
        "ref",
    }
)

_OPEN_SPDX = frozenset(
    {
        "MIT",
        "MIT-0",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "CC0-1.0",
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
        "MPL-2.0",
        "Zlib",
    }
)


def normalize_url(url: str) -> str:
    """Lowercase scheme/host, drop tracking params and fragments, sort query."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host
    if port is not None and (scheme, port) not in (("http", 80), ("https", 443)):
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    pairs = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    )
    return urlunsplit((scheme, netloc, path, urlencode(pairs), ""))


def normalize_arxiv_url(url: str) -> str:
    """Fold arXiv pdf links onto the canonical abs page."""
    normalized = normalize_url(url)
    parts = urlsplit(normalized)
    path = parts.path
    if path.startswith("/pdf/"):
        path = "/abs/" + path[len("/pdf/") :].removesuffix(".pdf")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def normalize_github_url(url: str) -> str:
    """Fold ``.git`` suffixes and trailing slashes onto /owner/repo."""
    normalized = normalize_url(url)
    parts = urlsplit(normalized)
    if parts.netloc != "github.com":
        return normalized
    path = parts.path.removesuffix("/").removesuffix(".git").lower()
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def normalize_source_url(url: str) -> str:
    host = (urlsplit(url.strip()).hostname or "").lower()
    if host.endswith("arxiv.org"):
        return normalize_arxiv_url(url)
    if host == "github.com":
        return normalize_github_url(url)
    return normalize_url(url)


def license_access_policy(license_value: str | None) -> AccessPolicy:
    """Open licenses persist; anything unclear stays metadata-only (ADR-0005)."""
    if not license_value:
        return AccessPolicy.METADATA_ONLY
    lowered = license_value.lower()
    if "creativecommons.org" in lowered:
        return AccessPolicy.PERSIST
    if license_value in _OPEN_SPDX:
        return AccessPolicy.PERSIST
    return AccessPolicy.METADATA_ONLY
