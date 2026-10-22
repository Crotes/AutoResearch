from __future__ import annotations

import pytest

from autoresearch.adapters.pi.protocol import (
    PI_PINNED_VERSION,
    JsonlDecoder,
    encode_record,
    is_response,
    parse_record,
    parse_response,
)
from autoresearch.domain import AutoResearchError, ErrorCategory


def test_pinned_version_matches_locked_pi_release() -> None:
    assert PI_PINNED_VERSION == "1.4.0"


def test_encode_record_produces_one_lf_terminated_line() -> None:
    payload = {"id": "req-1", "type": "get_state"}
    encoded = encode_record(payload)
    assert encoded.endswith(b"\n")
    assert encoded.count(b"\n") == 1
    assert parse_record(encoded[:-1]) == payload


def test_decoder_splits_records_on_lf_across_chunks() -> None:
    decoder = JsonlDecoder()
    first = encode_record({"type": "agent_start"})
    second = encode_record({"type": "agent_settled", "aborted": False})
    payload = first + second
    midpoint = len(first) - 1

    records = decoder.feed(payload[:midpoint])
    assert records == []
    records = decoder.feed(payload[midpoint:])
    assert [record["type"] for record in records] == ["agent_start", "agent_settled"]


def test_decoder_tolerates_crlf_and_blank_lines() -> None:
    decoder = JsonlDecoder()
    records = decoder.feed(b'{"type":"agent_start"}\r\n\r\n{"type":"turn_start"}\r\n')
    assert [record["type"] for record in records] == ["agent_start", "turn_start"]


def test_unicode_line_separators_inside_strings_are_not_frame_boundaries() -> None:
    # chr() keeps the raw U+2028/U+2029 out of the source file itself
    text = "第一行" + chr(0x2028) + "第二行" + chr(0x2029) + "第三行"
    record = {"type": "message_update", "delta": text}
    decoder = JsonlDecoder()
    records = decoder.feed(encode_record(record))
    assert records == [record]
    assert records[0]["delta"] == text


def test_flush_decodes_trailing_record_without_lf() -> None:
    decoder = JsonlDecoder()
    assert decoder.feed(b'{"type":"agent_start"}') == []
    assert decoder.flush() == [{"type": "agent_start"}]
    assert decoder.flush() == []


def test_bad_json_is_collected_as_protocol_error() -> None:
    decoder = JsonlDecoder()
    records = decoder.feed(b'{"type":"agent_start"}\nthis is not json\n{"type":"turn_start"}\n')
    assert [record["type"] for record in records] == ["agent_start", "turn_start"]
    errors = decoder.take_errors()
    assert len(errors) == 1
    failure = errors[0].failure
    assert failure.code == "pi.protocol_error"
    assert failure.category is ErrorCategory.INTERNAL
    assert decoder.take_errors() == []


def test_invalid_utf8_is_collected_as_protocol_error() -> None:
    decoder = JsonlDecoder()
    assert decoder.feed(b'{"type":"x","bad":"\xff\xfe"}\n') == []
    errors = decoder.take_errors()
    assert len(errors) == 1
    assert "UTF-8" in errors[0].failure.message


def test_parse_record_rejects_malformed_lines() -> None:
    with pytest.raises(AutoResearchError) as excinfo:
        parse_record(b"this is not json")
    assert excinfo.value.failure.code == "pi.protocol_error"


def test_record_without_string_type_is_rejected() -> None:
    with pytest.raises(AutoResearchError):
        parse_record(b'{"type":42}')
    with pytest.raises(AutoResearchError):
        parse_record(b'["not", "an", "object"]')


def test_parse_response_success_with_data() -> None:
    record = {
        "id": "req-1",
        "type": "response",
        "command": "get_state",
        "success": True,
        "data": {"isStreaming": False},
    }
    assert is_response(record)
    response = parse_response(record)
    assert response.id == "req-1"
    assert response.command == "get_state"
    assert response.success
    assert response.data == {"isStreaming": False}
    assert response.error is None


def test_parse_response_failure_and_parse_error_without_id() -> None:
    failed = parse_response(
        {
            "id": "req-3",
            "type": "response",
            "command": "set_model",
            "success": False,
            "error": "Model not found: invalid/model",
        }
    )
    assert not failed.success
    assert failed.error == "Model not found: invalid/model"

    parse_error = parse_response(
        {"type": "response", "command": "parse", "success": False, "error": "bad json"}
    )
    assert parse_error.id is None
    assert not parse_error.success
