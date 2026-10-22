from __future__ import annotations

from pathlib import Path

from autoresearch.application.content.html import extract_html_blocks

FIXTURES = Path(__file__).parents[1] / "fixtures" / "content"


def test_extracts_headings_and_paragraphs() -> None:
    blocks = extract_html_blocks((FIXTURES / "sample.html").read_text(encoding="utf-8"))
    headings = [block for block in blocks if block.kind == "heading"]
    paragraphs = [block for block in blocks if block.kind == "paragraph"]

    assert [block.text for block in headings] == [
        "Adaptive Memory for Long-Lived Agents",
        "Adaptive Memory for Long-Lived Agents",
        "Evaluation",
    ]
    assert any("pruning and consolidating" in block.text for block in paragraphs)
    assert any("Evidence is preliminary" in block.text for block in paragraphs)


def test_scripts_and_styles_are_dropped() -> None:
    blocks = extract_html_blocks((FIXTURES / "sample.html").read_text(encoding="utf-8"))
    joined = " ".join(block.text for block in blocks)
    assert "track()" not in joined
    assert "color: black" not in joined
