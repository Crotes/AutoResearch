from __future__ import annotations

from pathlib import Path

from autoresearch.application.content.detect import ContentFormat, detect_format

FIXTURES = Path(__file__).parents[1] / "fixtures" / "content"


def test_pdf_magic_bytes_win() -> None:
    body = (FIXTURES / "minimal.pdf").read_bytes()
    assert detect_format(body) is ContentFormat.PDF
    assert detect_format(body, "text/html") is ContentFormat.PDF


def test_html_by_media_type_and_by_doctype() -> None:
    assert detect_format(b"<p>hi</p>", "text/html; charset=utf-8") is ContentFormat.HTML
    assert detect_format(b"<!DOCTYPE html><html></html>") is ContentFormat.HTML
    assert detect_format(b"<html><body>x</body></html>") is ContentFormat.HTML


def test_markdown_heuristic() -> None:
    body = (FIXTURES / "sample.md").read_bytes()
    assert detect_format(body) is ContentFormat.MARKDOWN


def test_plain_text_fallback() -> None:
    body = (FIXTURES / "sample.txt").read_bytes()
    assert detect_format(body) is ContentFormat.TEXT
    assert detect_format(b"just a sentence.") is ContentFormat.TEXT
