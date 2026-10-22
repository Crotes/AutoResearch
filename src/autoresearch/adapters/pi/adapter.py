"""Pi-backed WorkerRuntime: one ResearchRun per `pi --mode rpc` process.

Pi's JSONL stream, session files, and process lifecycle stay inside this
adapter; upper layers only see `ResearchRun` snapshots and normalized domain
events. Raw Pi records are mirrored to `.autoresearch/sessions/<run_id>/` as an
audit attachment.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import threading
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any
from uuid import uuid4

from autoresearch.adapters.pi.events import (
    NormalizerState,
    classify_error,
    normalize_record,
)
from autoresearch.adapters.pi.process import DEFAULT_COMMAND_TIMEOUT, PiProcess
from autoresearch.adapters.pi.protocol import is_response
from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure
from autoresearch.domain.events import DomainEvent, EventKind, EventPage
from autoresearch.domain.models import ResearchRun, RunSpec, RunStatus

Clock = Callable[[], datetime]

_TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _RunContext:
    def __init__(
        self,
        run: ResearchRun,
        spec: RunSpec,
        process: PiProcess,
        audit: IO[str],
        watchdog: threading.Timer,
    ) -> None:
        self.lock = threading.Lock()
        self.run = run
        self.spec = spec
        self.process = process
        self.audit = audit
        self.watchdog = watchdog
        self.events: list[DomainEvent] = []
        self.normalizer = NormalizerState()


class PiRuntimeAdapter:
    """WorkerRuntime implementation backed by supervised Pi RPC subprocesses."""

    def __init__(
        self,
        *,
        pi_command: Sequence[str] | None = None,
        session_root: Path = Path(".autoresearch/sessions"),
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
        shutdown_timeout: float = 5.0,
        clock: Clock = _utc_now,
    ) -> None:
        if pi_command is None:
            # Windows CreateProcess 不做 PATHEXT 查找: 裸 "pi" 无法解析到 pi.cmd
            resolved = shutil.which("pi")
            pi_command = (resolved,) if resolved else ("pi",)
        self._pi_command = tuple(pi_command)
        self._session_root = session_root
        self._command_timeout = command_timeout
        self._shutdown_timeout = shutdown_timeout
        self._clock = clock
        self._lock = threading.Lock()
        self._runs: dict[str, _RunContext] = {}

    def start(self, spec: RunSpec) -> str:
        run_id = f"run-{uuid4().hex[:12]}"
        session_dir = self._session_root / run_id
        session_dir.mkdir(parents=True, exist_ok=True)
        audit = (session_dir / "pi-events.jsonl").open("a", encoding="utf-8")
        process = PiProcess(
            (*self._pi_command, "--mode", "rpc", "--session-dir", str(session_dir)),
            on_record=lambda record: self._on_record(run_id, record),
            on_protocol_error=lambda error: self._on_protocol_error(run_id, error),
            on_exit=lambda returncode: self._on_exit(run_id, returncode),
        )
        try:
            process.start()
        except AutoResearchError:
            audit.close()
            raise

        now = self._clock()
        run = ResearchRun(
            id=run_id,
            project_id=spec.project_id,
            status=RunStatus.RUNNING,
            plan=spec.plan,
            workflow_version=spec.workflow_version,
            created_at=now,
            updated_at=now,
        )
        watchdog = threading.Timer(
            spec.max_duration_seconds, self._on_budget_exceeded, args=(run_id,)
        )
        watchdog.daemon = True
        ctx = _RunContext(run, spec, process, audit, watchdog)
        with self._lock:
            self._runs[run_id] = ctx
        watchdog.start()
        self._emit(ctx, EventKind.RUN_STARTED, {"workflow_version": spec.workflow_version})
        self._send_prompt(ctx, _render_initial_prompt(spec))
        return run_id

    def events(self, run_id: str, cursor: int = 0) -> EventPage:
        ctx = self._require(run_id)
        with ctx.lock:
            events = tuple(ctx.events)
        if cursor < 0 or cursor > len(events):
            raise ValueError("event cursor is outside the event stream")
        return EventPage(events=events[cursor:], next_cursor=len(events))

    def cancel(self, run_id: str) -> None:
        ctx = self._require(run_id)
        with ctx.lock:
            status = ctx.run.status
        if status in {RunStatus.COMPLETED, RunStatus.CANCELLED}:
            return
        with contextlib.suppress(AutoResearchError):
            ctx.process.command("abort", timeout=self._command_timeout)
        self._mark_cancelled(ctx, force=True)

    def resume(self, run_id: str) -> None:
        ctx = self._require(run_id)
        with ctx.lock:
            status = ctx.run.status
        if status in {RunStatus.COMPLETED, RunStatus.CANCELLED}:
            return
        self._send_prompt(ctx, _render_resume_prompt(ctx.run), step="analyze_selected")

    def inspect(self, run_id: str) -> ResearchRun:
        ctx = self._require(run_id)
        with ctx.lock:
            return ctx.run

    def dispose(self, run_id: str) -> None:
        with self._lock:
            ctx = self._runs.pop(run_id, None)
        if ctx is None:
            return
        ctx.watchdog.cancel()
        ctx.process.close(
            graceful_timeout=self._shutdown_timeout, kill_timeout=self._shutdown_timeout
        )
        ctx.audit.close()

    def _send_prompt(
        self, ctx: _RunContext, message: str, *, step: str = "collect_sources"
    ) -> None:
        with ctx.lock:
            ctx.normalizer = replace(ctx.normalizer, step=step)
        try:
            response = ctx.process.command(
                "prompt", {"message": message}, timeout=self._command_timeout
            )
        except AutoResearchError as error:
            self._fail_run(ctx, error.failure)
            return
        if not response.success:
            self._fail_run(
                ctx,
                Failure(
                    category=classify_error(response.error or "prompt rejected"),
                    code="pi.command_failed",
                    message=response.error or "pi rejected the prompt",
                ),
            )
        elif isinstance(response.data, dict) and response.data.get("disposition") == "handled":
            self._complete_run(ctx)

    def _on_record(self, run_id: str, record: dict[str, Any]) -> None:
        ctx = self._runs.get(run_id)
        if ctx is None:
            return
        with ctx.lock:
            ctx.audit.write(json.dumps(record, ensure_ascii=False) + "\n")
            ctx.audit.flush()
        if is_response(record):
            return
        with ctx.lock:
            normalized, ctx.normalizer = normalize_record(record, ctx.normalizer)
        for event in normalized:
            self._apply(ctx, event.kind, event.data)

    def _on_protocol_error(self, run_id: str, error: AutoResearchError) -> None:
        ctx = self._runs.get(run_id)
        if ctx is None:
            return
        self._emit(
            ctx,
            EventKind.STEP_FAILED,
            {
                "step": ctx.normalizer.step,
                "category": error.failure.category,
                "code": error.failure.code,
                "message": error.failure.message,
            },
        )

    def _on_exit(self, run_id: str, returncode: int | None) -> None:
        ctx = self._runs.get(run_id)
        if ctx is None:
            return
        with ctx.lock:
            status = ctx.run.status
            step = ctx.normalizer.step
        if status is RunStatus.RUNNING:
            self._fail_run(
                ctx,
                Failure(
                    category=ErrorCategory.TRANSIENT,
                    code="pi.process_exited",
                    message=f"pi process exited unexpectedly with code {returncode}",
                    details={"returncode": returncode, "stderr": ctx.process.stderr_tail()},
                ),
                step=step,
            )

    def _on_budget_exceeded(self, run_id: str) -> None:
        ctx = self._runs.get(run_id)
        if ctx is None:
            return
        with ctx.lock:
            if ctx.run.status is not RunStatus.RUNNING:
                return
        self._fail_run(
            ctx,
            Failure(
                category=ErrorCategory.TRANSIENT,
                code="pi.budget_exceeded",
                message=(
                    f"run exceeded its duration budget of "
                    f"{ctx.spec.max_duration_seconds}s and was aborted"
                ),
            ),
        )
        with contextlib.suppress(AutoResearchError):
            ctx.process.command("abort", timeout=self._command_timeout)

    def _apply(self, ctx: _RunContext, kind: EventKind, data: dict[str, Any]) -> None:
        if kind is EventKind.RUN_COMPLETED:
            with ctx.lock:
                if ctx.run.status in _TERMINAL_STATUSES:
                    return
            self._emit(ctx, kind, data)
            self._complete_run(ctx)
        elif kind is EventKind.RUN_CANCELLED:
            self._mark_cancelled(ctx)
        else:
            self._emit(ctx, kind, data)
            if kind is EventKind.STEP_FAILED and data.get("will_retry") is False:
                self._transition_failed(ctx)

    def _complete_run(self, ctx: _RunContext) -> None:
        with ctx.lock:
            if ctx.run.status in _TERMINAL_STATUSES:
                return
        ctx.watchdog.cancel()
        self._set_status(ctx, RunStatus.COMPLETED, checkpoint="completed")

    def _transition_failed(self, ctx: _RunContext) -> None:
        """Move a run to FAILED after a terminal step failure was emitted."""
        with ctx.lock:
            if ctx.run.status in _TERMINAL_STATUSES:
                return
        ctx.watchdog.cancel()
        self._set_status(ctx, RunStatus.FAILED)

    def _mark_cancelled(self, ctx: _RunContext, *, force: bool = False) -> None:
        with ctx.lock:
            if ctx.run.status is RunStatus.CANCELLED:
                return
            checkpoint = ctx.run.checkpoint
            failed = ctx.run.status is RunStatus.FAILED
        if failed and not force:
            return
        ctx.watchdog.cancel()
        self._emit(ctx, EventKind.RUN_CANCELLED, {"checkpoint": checkpoint})
        self._set_status(ctx, RunStatus.CANCELLED)

    def _fail_run(self, ctx: _RunContext, failure: Failure, *, step: str | None = None) -> None:
        with ctx.lock:
            if ctx.run.status in _TERMINAL_STATUSES:
                return
        self._emit(
            ctx,
            EventKind.STEP_FAILED,
            {
                "step": step or ctx.normalizer.step,
                "category": failure.category,
                "code": failure.code,
                "message": failure.message,
            },
        )
        self._transition_failed(ctx)

    def _emit(self, ctx: _RunContext, kind: EventKind, data: dict[str, Any]) -> None:
        with ctx.lock:
            ctx.events.append(
                DomainEvent(
                    id=f"event-{uuid4().hex}",
                    run_id=ctx.run.id,
                    sequence=len(ctx.events),
                    kind=kind,
                    occurred_at=self._clock(),
                    data=dict(data),
                )
            )

    def _set_status(
        self, ctx: _RunContext, status: RunStatus, *, checkpoint: str | None = None
    ) -> None:
        with ctx.lock:
            ctx.run = replace(
                ctx.run,
                status=status,
                checkpoint=ctx.run.checkpoint if checkpoint is None else checkpoint,
                updated_at=self._clock(),
            )

    def _require(self, run_id: str) -> _RunContext:
        with self._lock:
            try:
                return self._runs[run_id]
            except KeyError as error:
                raise KeyError(f"unknown run: {run_id}") from error


def _render_initial_prompt(spec: RunSpec) -> str:
    plan = spec.plan
    lines = [
        "你是一名研究采集 Agent。请围绕下面的研究问题收集资料并给出概述。",
        f"研究问题: {plan.question}",
        "包含关键词: " + ", ".join(plan.include_terms),
    ]
    if plan.exclude_terms:
        lines.append("排除关键词: " + ", ".join(plan.exclude_terms))
    if plan.seed_urls:
        lines.append("种子来源: " + ", ".join(plan.seed_urls))
    lines.append(f"候选来源上限: {spec.max_candidates}")
    lines.append("完成后, 在最后一条消息中输出一个 JSON 对象, 总结要点与来源列表。")
    return "\n".join(lines)


def _render_resume_prompt(run: ResearchRun) -> str:
    return (
        f"人工审核已通过。请继续研究问题「{run.plan.question}」的分析与综合阶段, "
        "并在最终消息中输出一个 JSON 对象作为综合结果。"
    )
