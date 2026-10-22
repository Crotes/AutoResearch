"""RSS 2.0 / Atom feed connector restricted to an allowlist of feeds."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from autoresearch.adapters.sources.http import HttpClient
from autoresearch.adapters.sources.normalize import normalize_url
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

_ATOM = "{http://www.w3.org/2005/Atom}"
_TAG = re.compile(r"<[^>]+>")

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _policy_failure(message: str) -> AutoResearchError:
    return AutoResearchError(
        Failure(category=ErrorCategory.POLICY, code="rss.feed_not_allowed", message=message)
    )


@dataclass(frozen=True, slots=True)
class FeedItem:
    feed_url: str
    item_id: str
    title: str
    link: str
    summary: str
    published: str


class RssSource:
    """Only allowlisted feeds are fetched; an empty allowlist rejects all."""

    def __init__(
        self,
        http: HttpClient,
        *,
        allowed_feeds: Iterable[str] = (),
        clock: Clock = _utc_now,
    ) -> None:
        self._http = http
        self._allowed = frozenset(normalize_url(url) for url in allowed_feeds)
        self._clock = clock

    def discover(self, plan: ResearchPlan) -> Iterable[Candidate]:
        del plan  # feeds are allowlisted, not query-driven
        for feed_url in sorted(self._allowed):
            for item in self._fetch_feed(feed_url):
                yield Candidate(
                    source_ref=SourceRef(kind=SourceKind.RSS, locator=f"{feed_url}#{item.item_id}"),
                    title=item.title,
                    canonical_url=item.link,
                    metadata={
                        "work_id": f"{feed_url}#{item.item_id}",
                        "feed": feed_url,
                        "published": item.published,
                    },
                )

    def materialize(self, source_ref: SourceRef) -> SourceDocument:
        feed_url, separator, item_id = source_ref.locator.partition("#")
        if not separator or normalize_url(feed_url) not in self._allowed:
            raise _policy_failure(f"feed is not on the allowlist: {feed_url!r}")
        normalized_feed = normalize_url(feed_url)
        for item in self._fetch_feed(normalized_feed):
            if item.item_id == item_id:
                return self._document(source_ref, normalized_feed, item)
        raise AutoResearchError(
            Failure(
                category=ErrorCategory.PERMANENT,
                code="rss.unknown_item",
                message=f"no item {item_id!r} in feed {normalized_feed!r}",
            )
        )

    def _document(self, source_ref: SourceRef, feed_url: str, item: FeedItem) -> SourceDocument:
        text = _strip_tags(item.summary)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        version = SourceVersion(
            id=f"rss-{digest[:12]}",
            work_id=f"{feed_url}#{item.item_id}",
            source_ref=source_ref,
            canonical_url=item.link,
            retrieved_at=self._clock(),
            content_hash=digest,
            access_policy=AccessPolicy.METADATA_ONLY,
            license=None,
        )
        return SourceDocument(source_version=version, media_type="text/plain", text="", chunks=())

    def _fetch_feed(self, feed_url: str) -> list[FeedItem]:
        body = self._http.get(feed_url, cache_response=False).body
        try:
            root = ET.fromstring(body)
        except ET.ParseError as error:
            raise AutoResearchError(
                Failure(
                    category=ErrorCategory.CONTENT,
                    code="rss.parse_error",
                    message=f"feed {feed_url!r} is not valid XML: {error}",
                )
            ) from error
        if root.tag == f"{_ATOM}feed":
            return self._parse_atom(root, feed_url)
        return self._parse_rss(root, feed_url)

    def _parse_rss(self, root: ET.Element, feed_url: str) -> list[FeedItem]:
        items: list[FeedItem] = []
        for item in root.iter("item"):
            link = _text(item, "link")
            guid = _text(item, "guid") or link
            items.append(
                FeedItem(
                    feed_url=feed_url,
                    item_id=guid,
                    title=_text(item, "title"),
                    link=normalize_url(link) if link else feed_url,
                    summary=_text(item, "description"),
                    published=_text(item, "pubDate"),
                )
            )
        return items

    def _parse_atom(self, root: ET.Element, feed_url: str) -> list[FeedItem]:
        items: list[FeedItem] = []
        for entry in root.findall(f"{_ATOM}entry"):
            link = ""
            for link_element in entry.findall(f"{_ATOM}link"):
                if link_element.get("rel", "alternate") == "alternate":
                    link = link_element.get("href", "")
                    break
            item_id = _text(entry, "id", atom=True) or link
            items.append(
                FeedItem(
                    feed_url=feed_url,
                    item_id=item_id,
                    title=_text(entry, "title", atom=True),
                    link=normalize_url(link) if link else feed_url,
                    summary=_text(entry, "summary", atom=True)
                    or _text(entry, "content", atom=True),
                    published=_text(entry, "published", atom=True)
                    or _text(entry, "updated", atom=True),
                )
            )
        return items


def _text(element: ET.Element, tag: str, *, atom: bool = False) -> str:
    child = element.find(f"{_ATOM}{tag}" if atom else tag)
    return "" if child is None or child.text is None else child.text.strip()


def _strip_tags(value: str) -> str:
    return " ".join(_TAG.sub(" ", value).split())
