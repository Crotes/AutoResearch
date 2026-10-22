from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from autoresearch.application.content.pipeline import ContentProcessor
from autoresearch.domain.models import (
    AccessPolicy,
    SourceKind,
    SourceRef,
    SourceVersion,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "content"


def make_version(
    policy: AccessPolicy = AccessPolicy.PERSIST, version_id: str = "sv-1"
) -> SourceVersion:
    return SourceVersion(
        id=version_id,
        work_id="work-x",
        source_ref=SourceRef(kind=SourceKind.MANUAL_URL, locator="https://example.org/x"),
        canonical_url="https://example.org/x",
        retrieved_at=datetime(2024, 1, 1, tzinfo=UTC),
        content_hash="hash-x",
        access_policy=policy,
    )


def test_process_html_into_anchored_chunks() -> None:
    processor = ContentProcessor()
    raw = (FIXTURES / "sample.html").read_bytes()
    document, refs = processor.process_with_refs(make_version(), raw, "text/html")

    assert document.chunks
    assert document.text == "\n\n".join(document.chunks)
    assert refs[0].anchor == "sv-1#chunk-1"
    assert all(ref.page is None for ref in refs)
    assert all("track()" not in chunk for chunk in document.chunks)


def test_processing_is_idempotent_for_identical_content() -> None:
    processor = ContentProcessor()
    raw = (FIXTURES / "sample.md").read_bytes()
    first = processor.process(make_version(), raw, "text/markdown")
    second = processor.process(make_version(), raw, "text/markdown")
    assert first == second


def test_metadata_only_gate_strips_body() -> None:
    processor = ContentProcessor()
    raw = (FIXTURES / "sample.html").read_bytes()
    for policy in (AccessPolicy.METADATA_ONLY, AccessPolicy.CONTROLLED):
        document, refs = processor.process_with_refs(make_version(policy), raw, "text/html")
        assert document.text == ""
        assert document.chunks == ()
        assert refs == ()


def test_pdf_pipeline_keeps_page_anchors() -> None:
    processor = ContentProcessor()
    raw = (FIXTURES / "minimal.pdf").read_bytes()
    document, refs = processor.process_with_refs(make_version(), raw, "application/pdf")

    assert len(document.chunks) == 2
    assert refs[0].anchor == "sv-1#chunk-1@page-1"
    assert refs[1].anchor == "sv-1#chunk-2@page-2"
    assert refs[0].page == 1
