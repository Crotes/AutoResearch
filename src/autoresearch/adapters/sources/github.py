"""GitHub REST connector: repo metadata, README, and the latest release only."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from autoresearch.adapters.sources.http import HttpClient
from autoresearch.adapters.sources.normalize import license_access_policy, normalize_github_url
from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure
from autoresearch.domain.models import (
    Candidate,
    ResearchPlan,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
)

API_URL = "https://api.github.com"

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GitHubSource:
    def __init__(
        self,
        http: HttpClient,
        *,
        token: str | None = None,
        clock: Clock = _utc_now,
        per_page: int = 30,
    ) -> None:
        self._http = http
        self._token = os.environ.get("GITHUB_TOKEN") if token is None else token
        self._clock = clock
        self._per_page = per_page

    def discover(self, plan: ResearchPlan) -> Iterable[Candidate]:
        if not plan.include_terms:
            return
        query = "+".join(quote(term) for term in plan.include_terms)
        url = f"{API_URL}/search/repositories?q={query}&per_page={self._per_page}"
        payload = self._get_json(url)
        items = payload.get("items")
        if not isinstance(items, list):
            raise self._parse_failure("search response has no 'items' list")
        for item in items:
            yield self._candidate(item)

    def materialize(self, source_ref: SourceRef) -> SourceDocument:
        locator = source_ref.locator.removeprefix("github:").strip("/").lower()
        repo = self._get_json(f"{API_URL}/repos/{locator}")
        sections = [str(repo.get("description") or "")]
        readme = self._readme_text(locator)
        if readme:
            sections.append(readme)
        release = self._latest_release(locator)
        if release is not None:
            sections.append(
                f"Latest release {release.get('tag_name', '')}:\n{release.get('body', '')}"
            )
        text = "\n\n".join(section.strip() for section in sections if section.strip())
        license_info = repo.get("license")
        spdx = license_info.get("spdx_id") if isinstance(license_info, dict) else None
        if spdx in (None, "NOASSERTION"):
            spdx = None
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        version = SourceVersion(
            id=f"github-{locator.replace('/', '-')}-{digest[:12]}",
            work_id=locator,
            source_ref=source_ref,
            canonical_url=normalize_github_url(str(repo.get("html_url") or locator)),
            retrieved_at=self._clock(),
            content_hash=digest,
            access_policy=license_access_policy(spdx),
            license=spdx,
        )
        chunks = tuple(part for part in text.split("\n\n") if part.strip()) or (text,)
        return SourceDocument(
            source_version=version,
            media_type="text/plain",
            text=text,
            chunks=chunks,
        )

    def _candidate(self, item: dict[str, Any]) -> Candidate:
        full_name = str(item["full_name"])
        license_info = item.get("license")
        spdx = license_info.get("spdx_id") if isinstance(license_info, dict) else None
        return Candidate(
            source_ref=SourceRef(kind=SourceKind.GITHUB, locator=f"github:{full_name.lower()}"),
            title=full_name,
            canonical_url=normalize_github_url(str(item.get("html_url") or full_name)),
            metadata={
                "work_id": full_name.lower(),
                "stars": item.get("stargazers_count", 0),
                "license": spdx,
                "pushed_at": item.get("pushed_at"),
            },
        )

    def _readme_text(self, locator: str) -> str | None:
        try:
            payload = self._get_json(f"{API_URL}/repos/{locator}/readme")
        except AutoResearchError as error:
            if error.failure.code == "http.not_found":
                return None
            raise
        content = payload.get("content")
        if not isinstance(content, str):
            return None
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except ValueError:
            return None

    def _latest_release(self, locator: str) -> dict[str, Any] | None:
        try:
            payload = self._get_json(f"{API_URL}/repos/{locator}/releases/latest")
        except AutoResearchError as error:
            if error.failure.code == "http.not_found":
                return None
            raise
        return payload

    def _get_json(self, url: str) -> dict[str, Any]:
        response = self._http.get(url, headers=self._headers())
        try:
            payload = json.loads(response.body)
        except json.JSONDecodeError as error:
            raise self._parse_failure(f"invalid JSON from {url}: {error}") from error
        if not isinstance(payload, dict):
            raise self._parse_failure(f"unexpected JSON shape from {url}")
        return payload

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @staticmethod
    def _parse_failure(message: str) -> AutoResearchError:
        return AutoResearchError(
            Failure(category=ErrorCategory.CONTENT, code="github.parse_error", message=message)
        )
