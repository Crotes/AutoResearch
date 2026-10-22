"""End-to-end MCP stdio lifecycle against a real server subprocess."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from typing import Any

import pytest

INIT_PARAMS = {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "pytest", "version": "0"},
}


class StdioClient:
    def __init__(self) -> None:
        self._process = subprocess.Popen(
            [sys.executable, "-m", "autoresearch.adapters.mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self._lines: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self._next_id = 0

    def _read(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._lines.put(line)

    def send(self, message: dict[str, Any]) -> None:
        self.send_line(json.dumps(message, ensure_ascii=False) + "\n")

    def send_line(self, line: str) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        return self.read_response()

    def read_response(self, timeout: float = 10.0) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError("server did not respond within the timeout") from None
        return json.loads(line)

    def close(self) -> None:
        assert self._process.stdin is not None
        self._process.stdin.close()
        self._process.wait(timeout=10)

    @property
    def returncode(self) -> int | None:
        return self._process.returncode


@pytest.fixture()
def client() -> Any:
    stdio = StdioClient()
    try:
        yield stdio
    finally:
        if stdio.returncode is None:
            stdio.close()


def call_tool(client: StdioClient, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = client.request("tools/call", {"name": name, "arguments": arguments})
    assert "result" in response
    return response["result"]


def decode_result(result: dict[str, Any]) -> dict[str, Any]:
    assert result["content"][0]["type"] == "text"
    return json.loads(result["content"][0]["text"])


def test_full_mcp_stdio_lifecycle(client: StdioClient) -> None:
    initialized = client.request("initialize", INIT_PARAMS)
    assert initialized["result"]["serverInfo"]["name"] == "autoresearch-research-tools"
    assert initialized["result"]["capabilities"]["tools"] == {}

    client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    pong = client.request("ping")
    assert pong["result"] == {}

    listed = client.request("tools/list")
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert names == [
        "discover_sources",
        "materialize_source",
        "search_library",
        "read_source_chunks",
        "submit_artifact",
        "request_human_review",
    ]
    for tool in listed["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"

    discovered = decode_result(call_tool(client, "discover_sources", {}))
    assert discovered["candidates"]
    candidate = discovered["candidates"][0]

    materialized = decode_result(
        call_tool(
            client,
            "materialize_source",
            {"locator": candidate["locator"], "kind": candidate["kind"]},
        )
    )
    assert materialized["untrusted"] is True
    assert materialized["chunks"]

    chunks = decode_result(
        call_tool(
            client,
            "read_source_chunks",
            {"source_version_id": materialized["source_version_id"], "limit": 1},
        )
    )
    assert chunks["untrusted"] is True
    assert chunks["chunks"][0]["index"] == 0

    submitted = decode_result(
        call_tool(
            client,
            "submit_artifact",
            {
                "idempotency_key": "k-stdio",
                "kind": "overview",
                "markdown": "# 概述",
                "evidence_ids": [f"{materialized['source_version_id']}#chunk-0"],
            },
        )
    )
    assert submitted["idempotent_replay"] is False
    replay = decode_result(
        call_tool(
            client,
            "submit_artifact",
            {
                "idempotency_key": "k-stdio",
                "kind": "overview",
                "markdown": "# 概述",
                "evidence_ids": [f"{materialized['source_version_id']}#chunk-0"],
            },
        )
    )
    assert replay["idempotent_replay"] is True
    assert replay["artifact"]["artifact_id"] == submitted["artifact"]["artifact_id"]

    review = decode_result(call_tool(client, "request_human_review", {"gate": "source_selection"}))
    assert review == {"requested": True, "gate": "source_selection"}

    client.close()
    assert client.returncode == 0


def test_policy_violations_surface_as_is_error(client: StdioClient) -> None:
    client.request("initialize", INIT_PARAMS)

    traversal = call_tool(client, "read_source_chunks", {"source_version_id": "../etc/passwd"})
    assert traversal["isError"] is True
    assert decode_result(traversal)["failure"]["category"] == "policy"

    foreign = call_tool(client, "read_source_chunks", {"source_version_id": "source-foreign"})
    assert foreign["isError"] is True
    assert decode_result(foreign)["failure"]["category"] == "policy"

    disallowed = call_tool(
        client,
        "materialize_source",
        {"locator": "https://evil.example.net/paper"},
    )
    assert disallowed["isError"] is True
    assert decode_result(disallowed)["failure"]["category"] == "policy"

    no_evidence = call_tool(
        client,
        "submit_artifact",
        {"idempotency_key": "k", "kind": "overview", "markdown": "x", "evidence_ids": []},
    )
    assert no_evidence["isError"] is True
    assert decode_result(no_evidence)["failure"]["category"] == "policy"

    client.close()


def test_protocol_errors_and_unknown_methods(client: StdioClient) -> None:
    unknown = client.request("resources/list")
    assert unknown["error"]["code"] == -32601

    client.send_line("not json at all\n")
    parse_error = client.read_response()
    assert parse_error["error"]["code"] == -32700
    assert parse_error["id"] is None

    client.close()
