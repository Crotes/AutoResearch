"""Pi-backed WorkerRuntime: one ResearchRun per `pi --mode rpc` process.

Pi's JSONL stream, session files, and process lifecycle stay inside this
adapter; upper layers only see `ResearchRun` snapshots and normalized domain
events. Raw Pi records are mirrored to `.autoresearch/sessions/<run_id>/` as an
audit attachment.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
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
from autoresearch.application.workflow import WorkflowAction, WorkflowSnapshot, transition
from autoresearch.domain.errors import AutoResearchError, ErrorCategory, Failure
from autoresearch.domain.events import DomainEvent, EventKind, EventPage
from autoresearch.domain.models import ResearchRun, RunSpec, RunStatus
from autoresearch.ports.runtime import RuntimeSnapshot

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
        self.selected_work_ids: tuple[str, ...] = ()
        self.final_approved = False
        self.settled = threading.Event()
        self.model_configured = False


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
        run_env: Callable[[str], Mapping[str, str]] | None = None,
        model_provider: str | None = None,
        model_id: str | None = None,
        persist_run: Callable[[ResearchRun, RunSpec], None] | None = None,
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
        self._run_env = run_env
        self._model_provider = model_provider or os.environ.get("PI_MODEL_PROVIDER", "deepseek")
        self._model_id = model_id or os.environ.get("PI_MODEL_ID", "deepseek-flash")
        self._persist_run = persist_run
        self._lock = threading.Lock()
        self._runs: dict[str, _RunContext] = {}

    def start(self, spec: RunSpec) -> str:
        run_id = f"run-{uuid4().hex[:12]}"
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
        if self._persist_run is not None:
            # 必须在 spawn 之前落库: Pi 启动后立刻连接 MCP, MCP 需要从资料库读到该 run。
            self._persist_run(run, spec)
        session_dir = self._session_root / run_id
        session_dir.mkdir(parents=True, exist_ok=True)
        audit = (session_dir / "pi-events.jsonl").open("a", encoding="utf-8")
        process = self._spawn_process(run_id, session_dir)
        try:
            process.start()
        except AutoResearchError:
            audit.close()
            raise

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

    def restore(self, snapshot: RuntimeSnapshot) -> None:
        run_id = snapshot.run.id
        with self._lock:
            if run_id in self._runs:
                raise ValueError(f"run already active: {run_id}")
        session_dir = self._session_root / run_id
        session_dir.mkdir(parents=True, exist_ok=True)
        audit = (session_dir / "pi-events.jsonl").open("a", encoding="utf-8")
        process = self._spawn_process(run_id, session_dir)
        try:
            process.start()
        except AutoResearchError:
            audit.close()
            raise

        watchdog = threading.Timer(
            snapshot.spec.max_duration_seconds,
            self._on_budget_exceeded,
            args=(run_id,),
        )
        watchdog.daemon = True
        ctx = _RunContext(snapshot.run, snapshot.spec, process, audit, watchdog)
        ctx.events = list(snapshot.events)
        ctx.selected_work_ids = snapshot.selected_work_ids
        ctx.final_approved = snapshot.final_approved
        if snapshot.run.status is not RunStatus.RUNNING:
            ctx.settled.set()
        with self._lock:
            self._runs[run_id] = ctx
        if snapshot.run.status is RunStatus.RUNNING:
            watchdog.start()

    def _spawn_process(self, run_id: str, session_dir: Path) -> PiProcess:
        env = self._run_env(run_id) if self._run_env is not None else None
        return PiProcess(
            (*self._pi_command, "--mode", "rpc", "--session-dir", str(session_dir)),
            env=env,
            on_record=lambda record: self._on_record(run_id, record),
            on_protocol_error=lambda error: self._on_protocol_error(run_id, error),
            on_exit=lambda returncode: self._on_exit(run_id, returncode),
        )

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
            if ctx.run.status is RunStatus.COMPLETED:
                return
            previous_checkpoint = ctx.run.checkpoint
            updated = transition(self._snapshot(ctx), WorkflowAction.RESUME)
            self._apply_snapshot(ctx, updated)
        if updated.status is RunStatus.COMPLETED:
            ctx.watchdog.cancel()
            self._emit(ctx, EventKind.RUN_COMPLETED, {})
            return
        if previous_checkpoint == "overviews_ready":
            self._reset_watchdog(ctx)
            self._send_prompt(
                ctx,
                _render_resume_prompt(ctx.run, ctx.selected_work_ids),
                step="analyze_selected",
            )

    def review_selection(self, run_id: str, work_ids: Iterable[str]) -> None:
        ctx = self._require(run_id)
        selected = tuple(dict.fromkeys(work_ids))
        if not selected:
            raise ValueError("select at least one work")
        with ctx.lock:
            updated = transition(self._snapshot(ctx), WorkflowAction.RECORD_SELECTION)
            ctx.selected_work_ids = selected
            self._apply_snapshot(ctx, updated)

    def review_final(self, run_id: str, *, approved: bool) -> None:
        if not approved:
            raise ValueError("final review must be approved or the run cancelled")
        ctx = self._require(run_id)
        with ctx.lock:
            updated = transition(self._snapshot(ctx), WorkflowAction.APPROVE_FINAL)
            ctx.final_approved = True
            self._apply_snapshot(ctx, updated)

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

    def wait_for_settlement(self, run_id: str, timeout: float) -> None:
        """Block until the run leaves RUNNING (review gate, terminal, or timeout)."""
        self._require(run_id).settled.wait(timeout)

    def _send_prompt(
        self, ctx: _RunContext, message: str, *, step: str = "collect_sources"
    ) -> None:
        if not ctx.model_configured:
            ctx.model_configured = True
            if not self._configure_model(ctx):
                return
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
            self._advance_to_review(ctx)

    def _configure_model(self, ctx: _RunContext) -> bool:
        try:
            response = ctx.process.command(
                "set_model",
                {"provider": self._model_provider, "modelId": self._model_id},
                timeout=self._command_timeout,
            )
        except AutoResearchError as error:
            self._fail_run(ctx, error.failure)
            return False
        if not response.success:
            self._fail_run(
                ctx,
                Failure(
                    category=classify_error(response.error or "set_model rejected"),
                    code="pi.set_model_failed",
                    message=response.error or "pi rejected set_model",
                ),
            )
            return False
        return True

    def _on_record(self, run_id: str, record: dict[str, Any]) -> None:
        ctx = self._runs.get(run_id)
        if ctx is None:
            return
        with ctx.lock:
            ctx.audit.write(json.dumps(record, ensure_ascii=False) + "\n")
            ctx.audit.flush()
        if is_response(record):
            return
        if record.get("type") == "agent_settled" and not bool(record.get("aborted")):
            self._advance_to_review(ctx)
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
            self._advance_to_review(ctx)
        elif kind is EventKind.RUN_CANCELLED:
            self._mark_cancelled(ctx)
        else:
            self._emit(ctx, kind, data)
            if kind is EventKind.STEP_FAILED and data.get("will_retry") is False:
                self._transition_failed(ctx)

    def _advance_to_review(self, ctx: _RunContext) -> None:
        with ctx.lock:
            if ctx.run.status is not RunStatus.RUNNING:
                return
            if ctx.run.checkpoint is None:
                action = WorkflowAction.OVERVIEWS_READY
                gate = "source_selection"
            elif ctx.run.checkpoint == "overviews_ready":
                action = WorkflowAction.ANALYSES_READY
                gate = "final_approval"
            else:
                return
            updated = transition(self._snapshot(ctx), action)
            self._apply_snapshot(ctx, updated)
        ctx.watchdog.cancel()
        self._emit(ctx, EventKind.REVIEW_REQUESTED, {"gate": gate})

    def _reset_watchdog(self, ctx: _RunContext) -> None:
        ctx.watchdog.cancel()
        watchdog = threading.Timer(
            ctx.spec.max_duration_seconds,
            self._on_budget_exceeded,
            args=(ctx.run.id,),
        )
        watchdog.daemon = True
        ctx.watchdog = watchdog
        watchdog.start()

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
            self._sync_settled(ctx)

    @staticmethod
    def _snapshot(ctx: _RunContext) -> WorkflowSnapshot:
        return WorkflowSnapshot(
            status=ctx.run.status,
            checkpoint=ctx.run.checkpoint,
            has_selection=bool(ctx.selected_work_ids),
            final_approved=ctx.final_approved,
        )

    def _apply_snapshot(self, ctx: _RunContext, snapshot: WorkflowSnapshot) -> None:
        ctx.run = replace(
            ctx.run,
            status=snapshot.status,
            checkpoint=snapshot.checkpoint,
            updated_at=self._clock(),
        )
        self._sync_settled(ctx)

    def _sync_settled(self, ctx: _RunContext) -> None:
        if ctx.run.status is RunStatus.RUNNING:
            ctx.settled.clear()
        else:
            ctx.settled.set()

    def _require(self, run_id: str) -> _RunContext:
        with self._lock:
            try:
                return self._runs[run_id]
            except KeyError as error:
                raise KeyError(f"unknown run: {run_id}") from error


def _render_initial_prompt(spec: RunSpec) -> str:
    plan = spec.plan
    lines = [
        "你是一名研究采集 Agent. 只允许使用 research-tools MCP 服务器提供的工具; "
        "严禁用 bash/curl 或任何脚本直接访问外部网络或抓取网页.",
        "",
        f"研究问题: {plan.question}",
        "包含关键词: " + ", ".join(plan.include_terms),
    ]
    if plan.exclude_terms:
        lines.append("排除关键词: " + ", ".join(plan.exclude_terms))
    if plan.seed_urls:
        lines.append("种子来源: " + ", ".join(plan.seed_urls))
    lines.append(f"候选来源上限: {spec.max_candidates}")
    lines += [
        "",
        "严格按以下步骤执行, 每一步都必须通过 research-tools 工具完成:",
        "1. 调用 discover_sources 发现候选来源, 记录每个候选的 locator, kind 与 metadata.work_id.",
        "2. 对每个候选调用 materialize_source (locator 与 kind 取自上一步), "
        "得到 source_version_id.",
        "3. 需要正文时调用 read_source_chunks 读取该来源分块.",
        '4. 对每个候选调用 submit_artifact 提交速览: kind="overview", '
        'work_id 用该候选 metadata.work_id, evidence_ids 用 ["<source_version_id>#chunk-1"], '
        'skill_name="triage-sources", skill_version="1.0.0", '
        'idempotency_key 用稳定的 "overview-<work_id>", markdown 写一段简洁速览.',
        '5. 全部候选都提交速览后, 调用 request_human_review, gate="source_selection".',
        "6. 结束本轮, 等待人工选择. 不要生成详细解读或分类总结.",
    ]
    return "\n".join(lines)


def _render_resume_prompt(run: ResearchRun, selected_work_ids: tuple[str, ...]) -> str:
    return (
        "人工已选择以下成果: "
        + ", ".join(selected_work_ids)
        + ". 请继续研究问题 "
        + run.plan.question
        + " 的分析与综合阶段, 仍只允许使用 research-tools MCP 工具, "
        "严禁用 bash 访问外部网络:\n"
        "1. 对每个选中成果调用 read_source_chunks 读取已物化正文, 然后 submit_artifact 提交 "
        'kind="analysis" 的详细解读, work_id 用该成果 id, evidence_ids 用其来源分块锚点, '
        'skill_name="analyze-source", skill_version="1.0.0".\n'
        '2. 全部选中成果都完成解读后, submit_artifact 提交 kind="synthesis" 的分类总结, '
        '只引用选中成果及其证据, skill_name="synthesize-topic", skill_version="1.0.0".\n'
        '3. 调用 request_human_review, gate="final_approval", 然后结束本轮.'
    )
