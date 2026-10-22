"""Minimal JSON-RPC 2.0 peer for MCP over stdio.

MCP stdio frames one complete JSON-RPC message per line (newline-delimited
JSON). This module handles framing, request/notification parsing, method
dispatch, and the standard error codes; it knows nothing about tools.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import IO, Any

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

Handler = Callable[[dict[str, Any]], Any]


class JsonRpcFailure(Exception):
    """Raise inside a handler to reply with a JSON-RPC error response."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def encode_message(message: dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False) + "\n"


def make_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def make_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class JsonRpcServer:
    """Dispatch newline-delimited JSON-RPC requests to registered handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    def handle_line(self, line: str) -> str | None:
        """Process one framed line; returns a response line or None for notifications."""
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return encode_message(make_error(None, PARSE_ERROR, "invalid JSON"))
        response = self.handle_message(message)
        if response is None:
            return None
        return encode_message(response)

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return make_error(None, INVALID_REQUEST, "message must be a JSON object")
        request_id = message.get("id")
        is_notification = "id" not in message
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            if is_notification:
                return None
            return make_error(request_id, INVALID_REQUEST, "invalid JSON-RPC request")
        method = message["method"]
        handler = self._handlers.get(method)
        if handler is None:
            if is_notification:
                return None
            return make_error(request_id, METHOD_NOT_FOUND, f"unknown method: {method}")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return make_error(request_id, INVALID_PARAMS, "params must be an object")
        try:
            result = handler(params)
        except JsonRpcFailure as failure:
            if is_notification:
                return None
            return make_error(request_id, failure.code, failure.message)
        except Exception as error:  # a broken handler must not kill the serve loop
            if is_notification:
                return None
            return make_error(request_id, INTERNAL_ERROR, f"internal error: {error}")
        if is_notification:
            return None
        return make_result(request_id, result)

    def serve(self, stdin: IO[str], stdout: IO[str]) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            response = self.handle_line(line)
            if response is not None:
                stdout.write(response)
                stdout.flush()
