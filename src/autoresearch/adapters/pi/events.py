"""Pure normalization from Pi RPC records to domain event intentions.

The adapter threads one :class:`NormalizerState` per run through
:func:`normalize_record`; everything here is a pure function so fixtures can
drive it directly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from autoresearch.domain.errors import ErrorCategory
from autoresearch.domain.events import EventKind

_TRANSIENT_MARKERS = (
    "overloaded",
    "rate limit",
    "rate_limit",
    "timeout",
    "timed out",
    "connection",
    "terminated",
    "429",
    "500",
    "502",
    "503",
    "529",
)
_MODEL_MARKERS = ("not found", "invalid model", "auth", "api key", "permission", "provider")

_FENCED_BLOCK = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    kind: EventKind
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizerState:
    """Per-run normalization context; ``step`` names the current phase."""

    step: str = "collect_sources"
    artifacts: int = 0


def classify_error(message: str) -> ErrorCategory:
    """Map a Pi/provider error message onto a stable domain error category."""
    lowered = message.lower()
    if any(marker in lowered for marker in _TRANSIENT_MARKERS):
        return ErrorCategory.TRANSIENT
    if any(marker in lowered for marker in _MODEL_MARKERS):
        return ErrorCategory.MODEL
    return ErrorCategory.MODEL


def normalize_record(
    record: dict[str, Any], state: NormalizerState
) -> tuple[tuple[NormalizedEvent, ...], NormalizerState]:
    """Map one Pi record to zero or more domain events; audit-only records yield none."""
    record_type = record.get("type")

    if record_type == "agent_start":
        return (NormalizedEvent(EventKind.STEP_STARTED, {"step": state.step}),), state

    if record_type == "agent_settled":
        aborted = bool(record.get("aborted"))
        kind = EventKind.RUN_CANCELLED if aborted else EventKind.RUN_COMPLETED
        return (NormalizedEvent(kind, {}),), state

    if record_type == "message_end":
        return _normalize_message_end(record, state)

    if record_type == "auto_retry_start":
        message = str(record.get("errorMessage", "pi auto retry"))
        event = NormalizedEvent(
            EventKind.STEP_FAILED,
            {
                "step": state.step,
                "category": classify_error(message),
                "message": message,
                "attempt": record.get("attempt"),
                "will_retry": True,
            },
        )
        return (event,), state

    if record_type == "auto_retry_end" and not record.get("success", True):
        message = str(record.get("finalError", "pi auto retry exhausted"))
        event = NormalizedEvent(
            EventKind.STEP_FAILED,
            {
                "step": state.step,
                "category": classify_error(message),
                "message": message,
                "will_retry": False,
            },
        )
        return (event,), state

    if record_type == "message_update":
        nested = record.get("assistantMessageEvent")
        if isinstance(nested, dict) and nested.get("type") == "error":
            message = str(nested.get("error") or nested.get("reason") or "pi stream error")
            event = NormalizedEvent(
                EventKind.STEP_FAILED,
                {
                    "step": state.step,
                    "category": classify_error(message),
                    "message": message,
                    "will_retry": False,
                },
            )
            return (event,), state

    return (), state


def _normalize_message_end(
    record: dict[str, Any], state: NormalizerState
) -> tuple[tuple[NormalizedEvent, ...], NormalizerState]:
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return (), state
    if message.get("stopReason") == "error":
        error_message = str(message.get("errorMessage") or "pi assistant message failed")
        event = NormalizedEvent(
            EventKind.STEP_FAILED,
            {
                "step": state.step,
                "category": classify_error(error_message),
                "message": error_message,
                "will_retry": False,
            },
        )
        return (event,), state
    result = extract_structured_result(_assistant_text(message))
    if result is None:
        return (), state
    artifact_id = f"pi-artifact-{state.artifacts + 1}"
    event = NormalizedEvent(
        EventKind.ARTIFACT_CREATED,
        {"artifact_id": artifact_id, "kind": "synthesis", "result": result},
    )
    return (event,), replace(state, artifacts=state.artifacts + 1)


def _assistant_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def extract_structured_result(text: str) -> dict[str, Any] | None:
    """Extract a JSON object result from assistant text (whole body or fenced block)."""
    stripped = text.strip()
    if not stripped:
        return None
    candidates = [stripped]
    candidates.extend(match.group(1).strip() for match in _FENCED_BLOCK.finditer(stripped))
    opening = stripped.find("{")
    closing = stripped.rfind("}")
    if opening != -1 and closing > opening:
        candidates.append(stripped[opening : closing + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
