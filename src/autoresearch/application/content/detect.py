"""Format detection for raw source bodies."""

from __future__ import annotations

from enum import StrEnum


class ContentFormat(StrEnum):
    PDF = "pdf"
    HTML = "html"
    MARKDOWN = "markdown"
    TEXT = "text"


_MARKDOWN_MARKERS = ("# ", "## ", "- ", "```", "](", "> ")


def detect_format(body: bytes, media_type: str | None = None) -> ContentFormat:
    if body[:5] == b"%PDF-":
        return ContentFormat.PDF
    media = (media_type or "").split(";")[0].strip().lower()
    if media in ("text/html", "application/xhtml+xml"):
        return ContentFormat.HTML
    if media == "text/markdown":
        return ContentFormat.MARKDOWN
    head = body[:4096].decode("utf-8", errors="replace")
    lowered = head.lower()
    if "<!doctype html" in lowered or "<html" in lowered:
        return ContentFormat.HTML
    markers = sum(1 for line in head.splitlines() if line.lstrip().startswith(_MARKDOWN_MARKERS))
    if markers >= 2:
        return ContentFormat.MARKDOWN
    return ContentFormat.TEXT
