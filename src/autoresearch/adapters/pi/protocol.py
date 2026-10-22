"""Strict JSONL framing and record parsing for the Pi RPC protocol.

Pi speaks one JSON object per line on stdin/stdout. Records are framed by LF
only; a preceding CR is tolerated, while U+2028/U+2029 are valid inside JSON
strings and must never act as record boundaries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure

PI_PINNED_VERSION = "1.4.0"

_PROTOCOL_CODE = "pi.protocol_error"


def protocol_error(message: str, *, details: dict[str, Any] | None = None) -> AutoResearchError:
    return AutoResearchError(
        Failure(
            category=ErrorCategory.INTERNAL,
            code=_PROTOCOL_CODE,
            message=message,
            details={} if details is None else dict(details),
        )
    )


def encode_record(record: dict[str, Any]) -> bytes:
    """Serialize one protocol record as a single LF-terminated JSON line."""
    return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")


def parse_record(line: bytes) -> dict[str, Any]:
    """Parse one framed line into a protocol record, rejecting malformed input."""
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as error:
        raise protocol_error(f"pi record is not valid UTF-8: {error}") from error
    try:
        record = json.loads(text)
    except json.JSONDecodeError as error:
        raise protocol_error(f"pi record is not valid JSON: {error}") from error
    if not isinstance(record, dict) or not isinstance(record.get("type"), str):
        raise protocol_error("pi record must be a JSON object with a string 'type' field")
    return record


class JsonlDecoder:
    """Incremental byte-stream decoder that frames records on LF only.

    Malformed lines never discard neighbouring records: they are collected in
    ``errors`` and decoding continues with the next line.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._errors: list[AutoResearchError] = []

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self._buffer.extend(data)
        return self._drain()

    def flush(self) -> list[dict[str, Any]]:
        """Decode a trailing record that ended at EOF without a final LF."""
        return self.feed(b"\n")

    def take_errors(self) -> list[AutoResearchError]:
        errors = self._errors
        self._errors = []
        return errors

    def _drain(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        while (index := self._buffer.find(b"\n")) != -1:
            line = bytes(self._buffer[:index])
            del self._buffer[: index + 1]
            try:
                record = _parse_line(line)
            except AutoResearchError as error:
                self._errors.append(error)
                continue
            if record is not None:
                records.append(record)
        return records


def _parse_line(line: bytes) -> dict[str, Any] | None:
    if line.endswith(b"\r"):
        line = line[:-1]
    if not line.strip():
        return None
    return parse_record(line)


@dataclass(frozen=True, slots=True)
class CommandResponse:
    """A `type: "response"` record correlated to a command by request id."""

    id: str | None
    command: str
    success: bool
    data: Any = None
    error: str | None = None


def is_response(record: dict[str, Any]) -> bool:
    return record.get("type") == "response"


def parse_response(record: dict[str, Any]) -> CommandResponse:
    request_id = record.get("id")
    command = record.get("command")
    error = record.get("error")
    return CommandResponse(
        id=request_id if isinstance(request_id, str) else None,
        command=command if isinstance(command, str) else "",
        success=bool(record.get("success")),
        data=record.get("data"),
        error=error if isinstance(error, str) else None,
    )
