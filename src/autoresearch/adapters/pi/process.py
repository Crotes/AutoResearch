"""Supervision of one `pi --mode rpc` child process.

Owns the stdout reader thread, a bounded stderr diagnostic buffer, request-id
correlation for command responses, command timeouts, and an orderly-to-forced
shutdown escalation. Protocol violations and process death surface to callers
as :class:`~autoresearch.domain.errors.AutoResearchError` failures.
"""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from autoresearch.adapters.pi.protocol import (
    CommandResponse,
    JsonlDecoder,
    encode_record,
    is_response,
    parse_response,
)
from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure

DEFAULT_COMMAND_TIMEOUT = 30.0
_STDERR_BUFFER_LINES = 200


def _failure(category: ErrorCategory, code: str, message: str) -> AutoResearchError:
    return AutoResearchError(Failure(category=category, code=code, message=message))


@dataclass(slots=True)
class _Waiter:
    ready: threading.Event = field(default_factory=threading.Event)
    response: CommandResponse | None = None
    error: AutoResearchError | None = None


class PiProcess:
    """One supervised Pi RPC subprocess with correlated command round trips."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None = None,
        on_record: Callable[[dict[str, Any]], None] | None = None,
        on_protocol_error: Callable[[AutoResearchError], None] | None = None,
        on_exit: Callable[[int | None], None] | None = None,
    ) -> None:
        self._argv = tuple(argv)
        self._cwd = cwd
        self._on_record = on_record
        self._on_protocol_error = on_protocol_error
        self._on_exit = on_exit
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._pending: dict[str, _Waiter] = {}
        self._next_request = 0
        self._exited = False
        self._stderr_lines: deque[str] = deque(maxlen=_STDERR_BUFFER_LINES)
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            self._process = subprocess.Popen(
                list(self._argv),
                cwd=self._cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as error:
            raise _failure(
                ErrorCategory.INTERNAL, "pi.spawn_failed", f"failed to spawn pi: {error}"
            ) from error
        self._stdout_thread = threading.Thread(
            target=self._read_stdout, name="pi-stdout", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, name="pi-stderr", daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    @property
    def returncode(self) -> int | None:
        return None if self._process is None else self._process.poll()

    def stderr_tail(self) -> str:
        return "".join(self._stderr_lines)

    def command(
        self,
        command_type: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = DEFAULT_COMMAND_TIMEOUT,
    ) -> CommandResponse:
        """Send one command and wait for its correlated response."""
        record: dict[str, Any] = {"type": command_type}
        if payload:
            record.update(payload)
        with self._lock:
            if self._exited or self._process is None or self._process.stdin is None:
                raise _failure(
                    ErrorCategory.TRANSIENT,
                    "pi.process_exited",
                    "pi process is not running",
                )
            self._next_request += 1
            request_id = f"req-{self._next_request}"
            record["id"] = request_id
            waiter = _Waiter()
            self._pending[request_id] = waiter
            try:
                self._process.stdin.write(encode_record(record))
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                self._pending.pop(request_id, None)
                raise _failure(
                    ErrorCategory.TRANSIENT,
                    "pi.process_exited",
                    f"pi stdin is closed: {error}",
                ) from error
        if not waiter.ready.wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            raise _failure(
                ErrorCategory.TRANSIENT,
                "pi.command_timeout",
                f"pi command {command_type!r} timed out after {timeout}s",
            )
        if waiter.error is not None:
            raise waiter.error
        assert waiter.response is not None
        return waiter.response

    def close(self, *, graceful_timeout: float = 5.0, kill_timeout: float = 5.0) -> int | None:
        """Close stdin for an orderly exit, escalating to terminate then kill."""
        process = self._process
        if process is None:
            return None
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=graceful_timeout)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=kill_timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=kill_timeout)
        for stream in (process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread is not None:
                thread.join(timeout=kill_timeout)
        return process.returncode

    def _read_stdout(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        decoder = JsonlDecoder()
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                break
            self._feed(decoder, chunk)
        self._feed(decoder, b"", flush=True)
        self._handle_exit(process.wait())

    def _feed(self, decoder: JsonlDecoder, chunk: bytes, *, flush: bool = False) -> None:
        """Dispatch decoded records, reporting lines that violate the protocol."""
        records = decoder.flush() if flush else decoder.feed(chunk)
        self._dispatch(records)
        for error in decoder.take_errors():
            if self._on_protocol_error is not None:
                self._on_protocol_error(error)

    def _dispatch(self, records: list[dict[str, Any]]) -> None:
        for record in records:
            if is_response(record):
                response = parse_response(record)
                if response.id is not None:
                    with self._lock:
                        waiter = self._pending.pop(response.id, None)
                    if waiter is not None:
                        waiter.response = response
                        waiter.ready.set()
            if self._on_record is not None:
                self._on_record(record)

    def _read_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None
        for raw in process.stderr:
            self._stderr_lines.append(raw.decode("utf-8", errors="replace"))

    def _handle_exit(self, returncode: int | None) -> None:
        error = _failure(
            ErrorCategory.TRANSIENT,
            "pi.process_exited",
            f"pi process exited with code {returncode}: {self.stderr_tail().strip()}",
        )
        with self._lock:
            self._exited = True
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter.error = error
            waiter.ready.set()
        if self._on_exit is not None:
            self._on_exit(returncode)
