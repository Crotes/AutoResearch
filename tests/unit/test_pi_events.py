from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from autoresearch.adapters.pi.events import (
    NormalizedEvent,
    NormalizerState,
    classify_error,
    extract_structured_result,
    normalize_record,
)
from autoresearch.adapters.pi.protocol import JsonlDecoder
from autoresearch.domain import ErrorCategory, EventKind

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "pi"
EVENT_SCHEMA = json.loads((ROOT / "schemas" / "event.schema.json").read_text(encoding="utf-8"))


def load_fixture(name: str) -> tuple[list[dict[str, Any]], int]:
    decoder = JsonlDecoder()
    records = decoder.feed((FIXTURES / name).read_bytes())
    records.extend(decoder.flush())
    return records, len(decoder.take_errors())


def normalize_fixture(name: str) -> tuple[list[NormalizedEvent], int]:
    records, errors = load_fixture(name)
    state = NormalizerState()
    events: list[NormalizedEvent] = []
    for record in records:
        normalized, state = normalize_record(record, state)
        events.extend(normalized)
    return events, errors


def assert_events_satisfy_schema(events: list[NormalizedEvent]) -> None:
    validator = Draft202012Validator(EVENT_SCHEMA, format_checker=FormatChecker())
    for sequence, event in enumerate(events):
        document = {
            "id": f"event-{sequence}",
            "run_id": "run-fixture",
            "sequence": sequence,
            "kind": str(event.kind),
            "occurred_at": datetime.now(UTC).isoformat(),
            "data": json.loads(json.dumps(event.data, ensure_ascii=False)),
        }
        validator.validate(document)


def fixture_kinds(name: str) -> list[EventKind]:
    events, _ = normalize_fixture(name)
    assert_events_satisfy_schema(events)
    return [event.kind for event in events]


def test_happy_path_fixture_normalizes_to_completion() -> None:
    kinds = fixture_kinds("happy.jsonl")
    assert kinds == [
        EventKind.STEP_STARTED,
        EventKind.ARTIFACT_CREATED,
        EventKind.RUN_COMPLETED,
    ]
    events, _ = normalize_fixture("happy.jsonl")
    artifact = events[1]
    assert artifact.data["kind"] == "synthesis"
    assert artifact.data["result"]["summary"] == "固定样例研究结论"


def test_abort_fixture_normalizes_to_cancellation() -> None:
    assert fixture_kinds("abort.jsonl") == [EventKind.STEP_STARTED, EventKind.RUN_CANCELLED]


def test_retry_fixture_emits_transient_failure_then_completion() -> None:
    kinds = fixture_kinds("retry-then-settle.jsonl")
    assert kinds == [
        EventKind.STEP_STARTED,
        EventKind.STEP_FAILED,
        EventKind.ARTIFACT_CREATED,
        EventKind.RUN_COMPLETED,
    ]
    events, _ = normalize_fixture("retry-then-settle.jsonl")
    failure = events[1]
    assert failure.data["category"] is ErrorCategory.TRANSIENT
    assert failure.data["will_retry"] is True
    assert failure.data["attempt"] == 1


def test_invalid_json_fixture_yields_one_error_and_still_normalizes() -> None:
    events, errors = normalize_fixture("invalid-json.jsonl")
    assert errors == 1
    assert_events_satisfy_schema(events)
    assert [event.kind for event in events] == [
        EventKind.STEP_STARTED,
        EventKind.ARTIFACT_CREATED,
        EventKind.RUN_COMPLETED,
    ]


def test_mid_exit_fixture_only_records_the_started_step() -> None:
    assert fixture_kinds("mid-exit.jsonl") == [EventKind.STEP_STARTED]


def test_error_settle_fixture_emits_terminal_failures_before_completion() -> None:
    kinds = fixture_kinds("error-settle.jsonl")
    assert kinds == [
        EventKind.STEP_STARTED,
        EventKind.STEP_FAILED,
        EventKind.STEP_FAILED,
        EventKind.STEP_FAILED,
        EventKind.RUN_COMPLETED,
    ]
    events, _ = normalize_fixture("error-settle.jsonl")
    message_error = events[1]
    assert message_error.data["will_retry"] is False
    assert message_error.data["category"] is ErrorCategory.MODEL
    assert "invalid api key" in message_error.data["message"]
    # the terminal decision (FAILED, no run.completed) is the adapter's job,
    # exercised in tests/integration/test_pi_runtime.py


def test_message_end_with_error_stop_reason_produces_final_failure() -> None:
    record = {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [],
            "stopReason": "error",
            "errorMessage": "429 rate limit exceeded",
        },
    }
    events, _ = normalize_record(record, NormalizerState(step="collect_sources"))
    assert len(events) == 1
    assert events[0].kind is EventKind.STEP_FAILED
    assert events[0].data["will_retry"] is False
    assert events[0].data["category"] is ErrorCategory.TRANSIENT
    assert events[0].data["step"] == "collect_sources"


def test_message_update_error_maps_to_model_failure() -> None:
    record = {
        "type": "message_update",
        "assistantMessageEvent": {"type": "error", "reason": "error", "error": "model not found"},
    }
    events, _ = normalize_record(record, NormalizerState(step="collect_sources"))
    assert len(events) == 1
    assert events[0].kind is EventKind.STEP_FAILED
    assert events[0].data["category"] is ErrorCategory.MODEL
    assert events[0].data["step"] == "collect_sources"


def test_final_retry_failure_maps_to_failure_event() -> None:
    record = {"type": "auto_retry_end", "success": False, "finalError": "529 overloaded"}
    events, _ = normalize_record(record, NormalizerState())
    assert len(events) == 1
    assert events[0].kind is EventKind.STEP_FAILED
    assert events[0].data["will_retry"] is False
    assert events[0].data["category"] is ErrorCategory.TRANSIENT


def test_audit_only_records_produce_no_events() -> None:
    state = NormalizerState()
    for record in (
        {"type": "turn_start"},
        {"type": "tool_execution_start", "toolCallId": "c1", "toolName": "bash", "args": {}},
        {"type": "compaction_start", "reason": "threshold"},
        {"type": "queue_update", "steering": [], "followUp": []},
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "x"}},
    ):
        events, state = normalize_record(record, state)
        assert events == ()


def test_classify_error_categories() -> None:
    assert classify_error("529 overloaded") is ErrorCategory.TRANSIENT
    assert classify_error("rate limit exceeded") is ErrorCategory.TRANSIENT
    assert classify_error("Model not found: invalid/model") is ErrorCategory.MODEL
    assert classify_error("unknown provider error") is ErrorCategory.MODEL


def test_extract_structured_result_from_whole_text_and_fenced_block() -> None:
    assert extract_structured_result('{"a": 1}') == {"a": 1}
    fenced = '说明文字\n```json\n{"b": 2}\n```\n'
    assert extract_structured_result(fenced) == {"b": 2}
    assert extract_structured_result("没有结构化结果") is None
    assert extract_structured_result("[1, 2]") is None
