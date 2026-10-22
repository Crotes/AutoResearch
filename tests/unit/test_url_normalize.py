from __future__ import annotations

from autoresearch.adapters.sources.normalize import (
    license_access_policy,
    normalize_arxiv_url,
    normalize_github_url,
    normalize_source_url,
    normalize_url,
)
from autoresearch.domain import AccessPolicy


def test_scheme_and_host_are_lowercased() -> None:
    assert normalize_url("HTTP://Example.COM/Path") == "http://example.com/Path"


def test_tracking_params_removed_and_query_sorted() -> None:
    url = "https://example.org/page?b=2&utm_source=feed&a=1&gclid=xyz#frag"
    assert normalize_url(url) == "https://example.org/page?a=1&b=2"


def test_default_ports_are_dropped() -> None:
    assert normalize_url("http://example.org:80/a") == "http://example.org/a"
    assert normalize_url("https://example.org:443/a") == "https://example.org/a"
    assert normalize_url("https://example.org:8443/a") == "https://example.org:8443/a"


def test_arxiv_pdf_folds_onto_abs() -> None:
    assert normalize_arxiv_url("https://arxiv.org/pdf/2401.00001") == (
        "https://arxiv.org/abs/2401.00001"
    )
    assert normalize_arxiv_url("https://arxiv.org/pdf/2401.00001.pdf") == (
        "https://arxiv.org/abs/2401.00001"
    )
    assert normalize_source_url("HTTPS://ARXIV.ORG/pdf/2401.00001v2") == (
        "https://arxiv.org/abs/2401.00001v2"
    )


def test_github_repo_urls_are_canonicalized() -> None:
    assert normalize_github_url("https://github.com/Lab/Repo.git/") == (
        "https://github.com/lab/repo"
    )
    assert normalize_source_url("https://github.com/Lab/Repo/") == "https://github.com/lab/repo"
    other = "https://gitlab.com/Lab/Repo.git"
    assert normalize_github_url(other) == "https://gitlab.com/Lab/Repo.git"


def test_license_access_policy_mapping() -> None:
    assert license_access_policy("http://creativecommons.org/licenses/by/4.0/") is (
        AccessPolicy.PERSIST
    )
    assert license_access_policy("MIT") is AccessPolicy.PERSIST
    assert license_access_policy("Apache-2.0") is AccessPolicy.PERSIST
    assert license_access_policy(None) is AccessPolicy.METADATA_ONLY
    assert license_access_policy("Proprietary") is AccessPolicy.METADATA_ONLY
