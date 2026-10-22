"""arXiv Atom API connector."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from urllib.parse import quote

from autoresearch.adapters.sources.http import HttpClient
from autoresearch.adapters.sources.normalize import license_access_policy, normalize_arxiv_url
from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure
from autoresearch.domain.models import (
    Candidate,
    ResearchPlan,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
)

API_URL = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def arxiv_id_from_url(value: str) -> str:
    return value.rsplit("/abs/", 1)[-1].split("v")[0]


class ArxivSource:
    def __init__(
        self,
        http: HttpClient,
        *,
        clock: Clock = _utc_now,
        page_size: int = 50,
        max_pages: int = 2,
    ) -> None:
        self._http = http
        self._clock = clock
        self._page_size = page_size
        self._max_pages = max_pages

    def discover(self, plan: ResearchPlan) -> Iterable[Candidate]:
        if not plan.include_terms:
            return
        query = "+AND+".join(f'all:"{term}"' for term in plan.include_terms)
        for term in plan.exclude_terms:
            query += f'+ANDNOT+all:"{term}"'
        for page in range(self._max_pages):
            url = (
                f"{API_URL}?search_query={quote(query)}"
                f"&start={page * self._page_size}&max_results={self._page_size}"
            )
            entries = self._parse(self._http.get(url).body)
            if not entries:
                return
            for entry in entries:
                yield self._candidate(entry)
            if len(entries) < self._page_size:
                return

    def materialize(self, source_ref: SourceRef) -> SourceDocument:
        arxiv_id = source_ref.locator.removeprefix("arxiv:")
        url = f"{API_URL}?id_list={quote(arxiv_id)}"
        entries = self._parse(self._http.get(url).body)
        if not entries:
            raise AutoResearchError(
                Failure(
                    category=ErrorCategory.PERMANENT,
                    code="arxiv.unknown_id",
                    message=f"no arXiv entry for id {arxiv_id!r}",
                )
            )
        entry = entries[0]
        text = " ".join(self._text(entry, "summary").split())
        license_value = entry.findtext(f"{_ARXIV}license")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        version = SourceVersion(
            id=f"arxiv-{arxiv_id}-{digest[:12]}",
            work_id=arxiv_id,
            source_ref=source_ref,
            canonical_url=normalize_arxiv_url(self._text(entry, "id")),
            retrieved_at=self._clock(),
            content_hash=digest,
            access_policy=license_access_policy(license_value),
            license=license_value,
        )
        return SourceDocument(
            source_version=version,
            media_type="text/plain",
            text=text,
            chunks=(text,),
        )

    def _candidate(self, entry: ET.Element) -> Candidate:
        abs_url = self._text(entry, "id")
        arxiv_id = arxiv_id_from_url(abs_url)
        authors = [self._text(author, "name") for author in entry.findall(f"{_ATOM}author")]
        license_value = entry.findtext(f"{_ARXIV}license")
        return Candidate(
            source_ref=SourceRef(kind=SourceKind.ARXIV, locator=f"arxiv:{arxiv_id}"),
            title=" ".join(self._text(entry, "title").split()),
            canonical_url=normalize_arxiv_url(abs_url),
            metadata={
                "work_id": arxiv_id,
                "published": self._text(entry, "published"),
                "authors": authors,
                "license": license_value,
            },
        )

    def _parse(self, body: bytes) -> list[ET.Element]:
        try:
            root = ET.fromstring(body)
        except ET.ParseError as error:
            raise AutoResearchError(
                Failure(
                    category=ErrorCategory.CONTENT,
                    code="arxiv.parse_error",
                    message=f"arXiv response is not valid Atom XML: {error}",
                )
            ) from error
        return list(root.findall(f"{_ATOM}entry"))

    @staticmethod
    def _text(element: ET.Element, tag: str) -> str:
        child = element.find(f"{_ATOM}{tag}")
        return "" if child is None or child.text is None else child.text.strip()
