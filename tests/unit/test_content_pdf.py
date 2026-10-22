from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from autoresearch.application.content.pdf import extract_pdf_pages
from autoresearch.domain import AutoResearchError, ErrorCategory

FIXTURES = Path(__file__).parents[1] / "fixtures" / "content"


def test_minimal_pdf_yields_two_pages_with_text() -> None:
    pages = extract_pdf_pages((FIXTURES / "minimal.pdf").read_bytes())
    assert [page.page for page in pages] == [1, 2]
    assert "reviews failed trajectories" in pages[0].text
    assert "End of page.Done" in pages[0].text  # TJ array strings are joined
    assert "reflection improves success" in pages[1].text


def test_non_pdf_body_is_content_failure() -> None:
    with pytest.raises(AutoResearchError) as excinfo:
        extract_pdf_pages(b"not a pdf at all")
    assert excinfo.value.failure.category is ErrorCategory.CONTENT
    assert excinfo.value.failure.code == "pdf.extract_failed"


def test_corrupt_flate_stream_is_content_failure() -> None:
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Length 10 /Filter /FlateDecode >>\nstream\n"
        + zlib.compress(b"BT (x) Tj ET")[:5]
        + b"\nendstream\nendobj\n"
    )
    with pytest.raises(AutoResearchError) as excinfo:
        extract_pdf_pages(body)
    assert excinfo.value.failure.code == "pdf.extract_failed"


def test_pdf_without_text_streams_is_content_failure() -> None:
    body = b"%PDF-1.4\n1 0 obj\n<< /Length 4 >>\nstream\n1234\nendstream\nendobj\n"
    with pytest.raises(AutoResearchError, match="no extractable text"):
        extract_pdf_pages(body)
