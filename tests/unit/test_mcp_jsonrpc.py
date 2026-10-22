from __future__ import annotations

import json

from autoresearch.adapters.mcp.jsonrpc import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcFailure,
    JsonRpcServer,
    encode_message,
    make_result,
)


def make_server() -> JsonRpcServer:
    server = JsonRpcServer()
    server.register("echo", lambda params: {"echo": params})
    server.register("ping", lambda params: {})
    return server


def parse_line(line: str) -> dict:
    return json.loads(line)


def test_request_roundtrip() -> None:
    server = make_server()
    response = parse_line(server.handle_line('{"jsonrpc":"2.0","id":1,"method":"ping"}') or "")
    assert response == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_params_are_passed_to_handler() -> None:
    server = make_server()
    line = encode_message({"jsonrpc": "2.0", "id": "a", "method": "echo", "params": {"x": 1}})
    response = parse_line(server.handle_line(line) or "")
    assert response["result"] == {"echo": {"x": 1}}


def test_notification_produces_no_response() -> None:
    server = make_server()
    assert server.handle_line('{"jsonrpc":"2.0","method":"ping"}') is None
    assert server.handle_line('{"jsonrpc":"2.0","method":"nope"}') is None


def test_unknown_method_returns_method_not_found() -> None:
    server = make_server()
    response = parse_line(server.handle_line('{"jsonrpc":"2.0","id":9,"method":"nope"}') or "")
    assert response["id"] == 9
    assert response["error"]["code"] == METHOD_NOT_FOUND


def test_bad_json_returns_parse_error_with_null_id() -> None:
    server = make_server()
    response = parse_line(server.handle_line("this is not json") or "")
    assert response["id"] is None
    assert response["error"]["code"] == PARSE_ERROR


def test_invalid_request_shape_is_rejected() -> None:
    server = make_server()
    response = parse_line(server.handle_line('{"id": 2, "method": "ping"}') or "")
    assert response["error"]["code"] == INVALID_REQUEST
    response = parse_line(server.handle_line("[1, 2, 3]") or "")
    assert response["error"]["code"] == INVALID_REQUEST


def test_non_object_params_are_rejected() -> None:
    server = make_server()
    line = '{"jsonrpc":"2.0","id":3,"method":"echo","params":[1]}'
    response = parse_line(server.handle_line(line) or "")
    assert response["error"]["code"] == INVALID_PARAMS


def test_handler_failure_maps_to_error_response() -> None:
    server = JsonRpcServer()
    server.register("boom", lambda params: (_ for _ in ()).throw(JsonRpcFailure(42, "nope")))
    response = parse_line(server.handle_line('{"jsonrpc":"2.0","id":4,"method":"boom"}') or "")
    assert response["error"] == {"code": 42, "message": "nope"}


def test_unexpected_handler_exception_becomes_internal_error() -> None:
    server = JsonRpcServer()

    def broken(params: dict) -> None:
        raise RuntimeError("kaput")

    server.register("broken", broken)
    response = parse_line(server.handle_line('{"jsonrpc":"2.0","id":5,"method":"broken"}') or "")
    assert response["error"]["code"] == INTERNAL_ERROR
    assert "kaput" in response["error"]["message"]


def test_make_result_shape() -> None:
    assert make_result("x", {"a": 1}) == {"jsonrpc": "2.0", "id": "x", "result": {"a": 1}}
