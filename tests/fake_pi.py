"""Process-level Pi RPC test double driven by the FAKE_PI_SCENARIO env var.

Run as `python tests/fake_pi.py --mode rpc ...`; extra CLI flags are ignored.
Speaks strict JSONL on stdin/stdout and replays scripted session events.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

EVENT_DELAY = 0.02

_RESULT_TEXT = (
    '研究完成。\n\n```json\n{"summary": "固定样例研究结论", "sources": ["arxiv:2401.00001"]}\n```'
)


def emit(record: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    time.sleep(EVENT_DELAY)


def respond(request: dict[str, Any], *, success: bool = True, **fields: Any) -> None:
    record: dict[str, Any] = {
        "type": "response",
        "command": request.get("type", ""),
        "success": success,
    }
    if "id" in request:
        record["id"] = request["id"]
    record.update(fields)
    emit(record)


def user_message(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text, "timestamp": 1733234401000}


def assistant_message(text: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "stopReason": "stop",
        "timestamp": 1733234401001,
    }


def assistant_error_message(error: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [],
        "stopReason": "error",
        "errorMessage": error,
        "timestamp": 1733234401001,
    }


def emit_happy_run(prompt_text: str, *, with_retry: bool = False, bad_line: bool = False) -> None:
    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    emit({"type": "message_start", "message": user_message(prompt_text)})
    emit({"type": "message_end", "message": user_message(prompt_text)})
    if with_retry:
        emit(
            {
                "type": "auto_retry_start",
                "attempt": 1,
                "maxAttempts": 3,
                "delayMs": 2000,
                "errorMessage": "529 overloaded",
            }
        )
        emit({"type": "auto_retry_end", "success": True, "attempt": 2})
    if bad_line:
        sys.stdout.write("this is not json\n")
        sys.stdout.flush()
        time.sleep(EVENT_DELAY)
    emit({"type": "message_start", "message": assistant_message("")})
    emit(
        {
            "type": "message_update",
            "usage": {"input": 10, "output": 1, "totalTokens": 11},
            "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": "研"},
        }
    )
    emit({"type": "message_end", "message": assistant_message(_RESULT_TEXT)})
    emit({"type": "turn_end", "message": assistant_message(_RESULT_TEXT), "toolResults": []})
    emit({"type": "agent_end", "messages": [assistant_message(_RESULT_TEXT)], "willRetry": False})
    emit({"type": "agent_settled", "aborted": False})


class FakePi:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.running = False

    def handle(self, request: dict[str, Any]) -> None:
        command = request.get("type")
        if command == "prompt":
            self._on_prompt(request)
        elif command == "abort":
            self.running = False
            emit({"type": "agent_settled", "aborted": True})
            respond(request)
        elif command == "get_state":
            respond(
                request,
                data={
                    "isStreaming": self.running,
                    "sessionId": "fake-session",
                    "messageCount": 0,
                    "pendingMessageCount": 0,
                },
            )
        else:
            respond(request)

    def _on_prompt(self, request: dict[str, Any]) -> None:
        self.running = True
        respond(request, data={"disposition": "started"})
        message = str(request.get("message", ""))
        if self.scenario == "happy":
            emit_happy_run(message)
        elif self.scenario == "retry":
            emit_happy_run(message, with_retry=True)
        elif self.scenario == "bad_json":
            emit_happy_run(message, bad_line=True)
        elif self.scenario == "mid_exit":
            emit({"type": "agent_start"})
            os._exit(3)
        elif self.scenario == "error_settle":
            error = "401 Unauthorized: invalid api key"
            emit({"type": "agent_start"})
            emit({"type": "message_start", "message": assistant_message("")})
            emit({"type": "message_end", "message": assistant_error_message(error)})
            emit({"type": "agent_settled", "aborted": False})
        elif self.scenario in {"abort", "busy"}:
            emit({"type": "agent_start"})
            return
        else:
            emit({"type": "agent_settled", "aborted": False})
        self.running = False


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    scenario = os.environ.get("FAKE_PI_SCENARIO", "happy")
    fake = FakePi(scenario)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as error:
            emit(
                {
                    "type": "response",
                    "command": "parse",
                    "success": False,
                    "error": f"Failed to parse command: {error}",
                }
            )
            continue
        if isinstance(request, dict):
            fake.handle(request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
