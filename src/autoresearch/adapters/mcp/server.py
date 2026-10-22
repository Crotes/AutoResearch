"""MCP stdio server exposing the whitelisted research tools.

Binds the newline-delimited JSON-RPC peer to the six tool handlers. Each tool
call runs in a thread pool under a hard deadline; failures are classified into
domain ``Failure`` categories and returned as MCP ``isError`` results rather
than raised.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import IO, Any

from autoresearch import __version__
from autoresearch.adapters.mcp.jsonrpc import (
    INVALID_PARAMS,
    JsonRpcFailure,
    JsonRpcServer,
)
from autoresearch.adapters.mcp.tools import (
    TOOL_DEFINITIONS,
    TOOL_HANDLERS,
    ToolContext,
    ToolError,
)
from autoresearch.domain.errors import ErrorCategory, Failure

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "autoresearch-research-tools"
DEFAULT_TOOL_TIMEOUT = 30.0


class ResearchToolsServer:
    """Run-scoped MCP server: one instance serves one research run's tools."""

    def __init__(
        self,
        context: ToolContext,
        *,
        tool_timeout: float = DEFAULT_TOOL_TIMEOUT,
        max_workers: int = 4,
    ) -> None:
        self._context = context
        self._tool_timeout = tool_timeout
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._rpc = JsonRpcServer()
        self._rpc.register("initialize", self._on_initialize)
        self._rpc.register("notifications/initialized", self._on_initialized)
        self._rpc.register("ping", self._on_ping)
        self._rpc.register("tools/list", self._on_tools_list)
        self._rpc.register("tools/call", self._on_tools_call)

    def handle_line(self, line: str) -> str | None:
        return self._rpc.handle_line(line)

    def serve(self, stdin: IO[str], stdout: IO[str]) -> None:
        try:
            self._rpc.serve(stdin, stdout)
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _visible_tools(self) -> list[dict[str, Any]]:
        return [
            TOOL_DEFINITIONS[name]
            for name in TOOL_DEFINITIONS
            if name in self._context.allowed_tools
        ]

    def _on_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
        }

    def _on_initialized(self, params: dict[str, Any]) -> None:
        return None

    def _on_ping(self, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    def _on_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"tools": self._visible_tools()}

    def _on_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str):
            raise JsonRpcFailure(INVALID_PARAMS, "tools/call requires a string 'name'")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise JsonRpcFailure(INVALID_PARAMS, "tools/call 'arguments' must be an object")
        handler = TOOL_HANDLERS.get(name)
        if handler is None or name not in self._context.allowed_tools:
            failure = Failure(
                category=ErrorCategory.POLICY,
                code="mcp.tool_not_available",
                message=f"tool {name!r} is not available for this run",
            )
            return self._tool_result(failure)
        future = self._executor.submit(handler, self._context, arguments)
        try:
            result = future.result(timeout=self._tool_timeout)
        except FutureTimeout:
            failure = Failure(
                category=ErrorCategory.TRANSIENT,
                code="mcp.tool_timeout",
                message=f"tool {name!r} exceeded its {self._tool_timeout}s deadline",
            )
            return self._tool_result(failure)
        except ToolError as error:
            return self._tool_result(error.failure)
        except Exception as error:  # ports must not leak bare exceptions either
            failure = Failure(
                category=ErrorCategory.INTERNAL,
                code="mcp.tool_internal_error",
                message=f"tool {name!r} failed internally: {error}",
            )
            return self._tool_result(failure)
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "isError": False,
        }

    @staticmethod
    def _tool_result(failure: Failure) -> dict[str, Any]:
        payload = {
            "failure": {
                "category": str(failure.category),
                "code": failure.code,
                "message": failure.message,
                "retryable": failure.should_retry,
            }
        }
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": True,
        }
