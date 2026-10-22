"""Generate tests/fixtures/content/minimal.pdf — a tiny valid two-page PDF.

Each page has one FlateDecode content stream using Tj/TJ operators, which is
exactly the subset our stdlib extractor supports. Run: `python make_pdf.py`.
"""

from __future__ import annotations

import zlib
from pathlib import Path

PAGES = [
    "Self-Refining Language Agents. The agent reviews failed trajectories.",
    "Across three tasks, reflection improves success while adding inference cost.",
]


def content_stream(text: str) -> bytes:
    words = text.split(" ")
    parts = [f"BT /F1 12 Tf 72 720 Td ({words[0]}"]
    parts.extend(f" {word}" for word in words[1:])
    parts.append(") Tj [(End of page.) -250 (Done)] TJ ET")
    return "".join(parts).encode("latin-1")


def build() -> bytes:
    objects: list[bytes] = []
    kids = " ".join(f"{3 + index} 0 R" for index in range(len(PAGES)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(PAGES)} >>".encode())
    content_ids = []
    for index in range(len(PAGES)):
        content_id = 3 + len(PAGES) + index
        content_ids.append(content_id)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R "
                f"/Resources << /Font << /F1 {3 + 2 * len(PAGES)} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode()
        )
    for text in PAGES:
        stream = zlib.compress(content_stream(text))
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" /Filter /FlateDecode >>\n"
            b"stream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{number} 0 obj\n".encode())
        out.extend(body)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


if __name__ == "__main__":
    target = Path(__file__).parent / "minimal.pdf"
    target.write_bytes(build())
    print(f"wrote {target}")
