"""Minimal stdlib-only PDF text extraction.

Scans content streams, inflates FlateDecode data with zlib, and pulls text out
of Tj/TJ operators. One text-bearing stream is treated as one page so anchors
keep page numbers. Any structural problem degrades to a ``content`` Failure.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure

_LITERAL = rb"\((?:\\.|[^\\()])*\)"
_OPERATOR = re.compile(
    rb"(" + _LITERAL + rb")\s*Tj"  # (text) Tj
    rb"|\[((?:\\.|[^\]])*)\]\s*TJ"  # [(a) 250 (b)] TJ
    rb"|\b(?:Td|TD)\b|T\*"  # line positioning / new line
)
_ARRAY_STRING = re.compile(_LITERAL)
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\n?endstream", re.DOTALL)
_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "b": "\b",
    "f": "\f",
    "(": "(",
    ")": ")",
    "\\": "\\",
}


@dataclass(frozen=True, slots=True)
class PdfPage:
    page: int
    text: str


def extract_pdf_pages(body: bytes) -> tuple[PdfPage, ...]:
    if not body.startswith(b"%PDF-"):
        raise _content_failure("not a PDF document (missing %PDF- header)")
    pages: list[PdfPage] = []
    for match in _STREAM.finditer(body):
        stream = _inflate(match.group(1), body[: match.start()])
        if stream is None:
            continue
        text = _extract_text(stream)
        if text.strip():
            pages.append(PdfPage(page=len(pages) + 1, text=text))
    if not pages:
        raise _content_failure("no extractable text in PDF content streams")
    return tuple(pages)


def _inflate(stream: bytes, context: bytes) -> bytes | None:
    dictionary = context[-500:]
    if b"FlateDecode" not in dictionary:
        return stream if b"Tj" in stream or b"TJ" in stream else None
    try:
        return zlib.decompress(stream)
    except zlib.error as error:
        raise _content_failure(f"FlateDecode stream failed to inflate: {error}") from error


def _extract_text(content: bytes) -> str:
    parts: list[str] = []
    for match in _OPERATOR.finditer(content):
        literal, array = match.group(1), match.group(2)
        if literal is not None:
            parts.append(_decode_literal(literal[1:-1]))
        elif array is not None:
            parts.append(
                "".join(_decode_literal(item[1:-1]) for item in _ARRAY_STRING.findall(array))
            )
        else:
            parts.append("\n")
    return "".join(parts)


def _decode_literal(raw: bytes) -> str:
    out = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte == 0x5C and index + 1 < len(raw):  # backslash escape
            nxt = raw[index + 1]
            if 0x30 <= nxt <= 0x37:  # octal escape, up to 3 digits
                digits = bytes(raw[index + 1 : index + 4])
                end = 0
                while end < len(digits) and 0x30 <= digits[end] <= 0x37:
                    end += 1
                out.append(int(digits[:end], 8))
                index += 1 + end
                continue
            out.extend(_ESCAPES.get(chr(nxt), chr(nxt)).encode("latin-1"))
            index += 2
            continue
        out.append(byte)
        index += 1
    if out[:2] == b"\xfe\xff":
        return out[2:].decode("utf-16-be", errors="replace")
    return out.decode("latin-1")


def _content_failure(message: str) -> AutoResearchError:
    return AutoResearchError(
        Failure(category=ErrorCategory.CONTENT, code="pdf.extract_failed", message=message)
    )
