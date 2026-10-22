"""Pure normalization for source identifiers and canonical URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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

_ARXIV_VERSION = re.compile(r"v\d+$", re.IGNORECASE)


def strip_arxiv_version(value: str) -> str:
    """Remove only an arXiv version suffix, preserving legacy category names."""
    return _ARXIV_VERSION.sub("", value.strip())


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
    """Fold arXiv PDF links onto the canonical abstract page."""
    normalized = normalize_url(url)
    parts = urlsplit(normalized)
    path = parts.path
    if path.startswith("/pdf/"):
        path = "/abs/" + path[len("/pdf/") :].removesuffix(".pdf")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def normalize_github_url(url: str) -> str:
    """Fold Git suffixes and trailing slashes onto /owner/repo."""
    normalized = normalize_url(url)
    parts = urlsplit(normalized)
    if parts.netloc != "github.com":
        return normalized
    path = parts.path.removesuffix("/").removesuffix(".git").lower()
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
