"""HTML body extraction via stdlib html.parser (scripts/styles dropped)."""

from __future__ import annotations

from html.parser import HTMLParser

from autoresearch.application.content.chunk import Block, normalize_text

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_PARAGRAPH_TAGS = {"p", "li", "pre", "blockquote"}
_SKIP_TAGS = {"script", "style", "noscript", "template"}


class _BlockExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._buffer: list[str] = []
        self._kind = "paragraph"
        self._level = 0
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS or tag in _PARAGRAPH_TAGS or tag == "title":
            self._flush()
            self._kind = "heading" if tag in _HEADING_TAGS or tag == "title" else "paragraph"
            self._level = int(tag[1]) if tag in _HEADING_TAGS else 0

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _HEADING_TAGS or tag in _PARAGRAPH_TAGS or tag == "title":
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._buffer.append(data)

    def _flush(self) -> None:
        text = normalize_text(" ".join(self._buffer))
        self._buffer = []
        if text:
            self.blocks.append(Block(text=text, kind=self._kind))
        self._kind = "paragraph"
        self._level = 0

    def close(self) -> None:
        super().close()
        self._flush()


def extract_html_blocks(html: str) -> list[Block]:
    extractor = _BlockExtractor()
    extractor.feed(html)
    extractor.close()
    return extractor.blocks
