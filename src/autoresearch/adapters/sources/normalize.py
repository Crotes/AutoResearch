"""URL normalization and license-to-access-policy mapping shared by connectors."""

from __future__ import annotations

from urllib.parse import urlsplit

from autoresearch.domain.models import AccessPolicy
from autoresearch.domain.urls import (
    normalize_arxiv_url as normalize_arxiv_url,
)
from autoresearch.domain.urls import (
    normalize_github_url as normalize_github_url,
)
from autoresearch.domain.urls import (
    normalize_url as normalize_url,
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
