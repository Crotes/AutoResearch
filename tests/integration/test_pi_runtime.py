"""Drive the full WorkerRuntime lifecycle against a scripted fake Pi process.

Only `PiRuntimeAdapter` itself is imported from `autoresearch.adapters.pi`;
everything else goes through ports/domain types so this suite doubles as a
leak check for the runtime seam.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from autoresearch.adapters.pi import PiRuntimeAdapter
from autoresearch.domain import (
    AutoResearchError,
    ErrorCategory,
    EventKind,
    ResearchPlan,
    RunSpec,
    RunStatus,
    SourceKind,
)
from autoresearch.ports import WorkerRuntime

FAKE_PI = Path(__file__).parents[1] / "fake_pi.py"


def make_spec(max_duration_seconds: int = 60) -> RunSpec:
    return RunSpec(
        project_id="project-pi-runtime",
        plan=ResearchPlan(
            question="Agent 如何自进化?",
            include_terms=("agent self-evolution",),
            source_kinds=(SourceKind.ARXIV,),
        ),
        workflow_version="pi-poc-0.1.0",
        skill_versions={},
        max_duration_seconds=max_duration_seconds,
        max_candidates=5,
    )


def make_adapter(tmp_path: Path) -> PiRuntimeAdapter:
    return PiRuntimeAdapter(
        pi_command=(sys.executable, str(FAKE_PI)),
        session_root=tmp_path / "sessions",
        command_timeout=5.0,
        shutdown_timeout=2.0,
    )


def wait_for(predicate: Callable[[], bool], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met within the timeout")


def event_kinds(adapter: PiRuntimeAdapter, run_id: str) -> list[EventKind]:
    return [event.kind for event in adapter.events(run_id).events]


def test_adapter_satisfies_worker_runtime_port(tmp_path: Path) -> None:
    assert isinstance(make_adapter(tmp_path), WorkerRuntime)


def test_happy_run_requires_both_human_review_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "happy")
    adapter = make_adapter(tmp_path)
    run_id = adapter.start(make_spec())
    try:
        wait_for(
            lambda: adapter.inspect(run_id).status is RunStatus.REVIEW_REQUIRED,
            timeout=2.0,
        )

        run = adapter.inspect(run_id)
        assert run.checkpoint == "overviews_ready"
        assert event_kinds(adapter, run_id) == [
            EventKind.RUN_STARTED,
            EventKind.STEP_STARTED,
            EventKind.ARTIFACT_CREATED,
            EventKind.REVIEW_REQUESTED,
        ]

        with pytest.raises(ValueError, match="selection"):
            adapter.resume(run_id)
        adapter.review_selection(run_id, ("work-selected",))
        adapter.resume(run_id)
        wait_for(
            lambda: adapter.inspect(run_id).checkpoint == "analyses_ready",
            timeout=2.0,
        )
        assert adapter.inspect(run_id).status is RunStatus.REVIEW_REQUIRED

        with pytest.raises(ValueError, match="approval"):
            adapter.resume(run_id)
        adapter.review_final(run_id, approved=True)
        adapter.resume(run_id)
        assert adapter.inspect(run_id).status is RunStatus.COMPLETED
        assert adapter.inspect(run_id).checkpoint == "completed"

        page = adapter.events(run_id, cursor=1)
        assert page.events[0].kind is EventKind.STEP_STARTED
        assert page.next_cursor == len(adapter.events(run_id).events)
        with pytest.raises(ValueError, match="cursor"):
            adapter.events(run_id, cursor=99)

        audit = tmp_path / "sessions" / run_id / "pi-events.jsonl"
        audit_records = [
            json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()
        ]
        assert any(record.get("type") == "agent_settled" for record in audit_records)

        adapter.resume(run_id)
        assert adapter.inspect(run_id).status is RunStatus.COMPLETED
    finally:
        adapter.dispose(run_id)
    with pytest.raises(KeyError, match="unknown run"):
        adapter.inspect(run_id)


def test_cancel_running_run_marks_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "abort")
    adapter = make_adapter(tmp_path)
    run_id = adapter.start(make_spec())
    try:
        wait_for(lambda: EventKind.STEP_STARTED in event_kinds(adapter, run_id))
        adapter.cancel(run_id)

        assert adapter.inspect(run_id).status is RunStatus.CANCELLED
        assert EventKind.RUN_CANCELLED in event_kinds(adapter, run_id)
        adapter.cancel(run_id)
        assert event_kinds(adapter, run_id).count(EventKind.RUN_CANCELLED) == 1
    finally:
        adapter.dispose(run_id)


def test_budget_watchdog_aborts_and_marks_transient_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "busy")
    adapter = make_adapter(tmp_path)
    run_id = adapter.start(make_spec(max_duration_seconds=1))
    try:
        wait_for(lambda: adapter.inspect(run_id).status is RunStatus.FAILED)

        failures = [
            event for event in adapter.events(run_id).events if event.kind is EventKind.STEP_FAILED
        ]
        assert failures
        assert failures[-1].data["code"] == "pi.budget_exceeded"
        assert failures[-1].data["category"] is ErrorCategory.TRANSIENT
    finally:
        adapter.dispose(run_id)


def test_unexpected_process_exit_marks_transient_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "mid_exit")
    adapter = make_adapter(tmp_path)
    run_id = adapter.start(make_spec())
    try:
        wait_for(lambda: adapter.inspect(run_id).status is RunStatus.FAILED)

        failures = [
            event for event in adapter.events(run_id).events if event.kind is EventKind.STEP_FAILED
        ]
        assert failures[-1].data["code"] == "pi.process_exited"
        assert failures[-1].data["category"] is ErrorCategory.TRANSIENT
    finally:
        adapter.dispose(run_id)


def test_invalid_json_line_is_audited_without_breaking_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "bad_json")
    adapter = make_adapter(tmp_path)
    run_id = adapter.start(make_spec())
    try:
        wait_for(lambda: adapter.inspect(run_id).status is RunStatus.REVIEW_REQUIRED)

        kinds = event_kinds(adapter, run_id)
        assert EventKind.REVIEW_REQUESTED in kinds
        protocol_failures = [
            event
            for event in adapter.events(run_id).events
            if event.kind is EventKind.STEP_FAILED and event.data["code"] == "pi.protocol_error"
        ]
        assert len(protocol_failures) == 1
        assert protocol_failures[0].data["category"] is ErrorCategory.INTERNAL
    finally:
        adapter.dispose(run_id)


def test_auto_retry_then_settle_requests_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "retry")
    adapter = make_adapter(tmp_path)
    run_id = adapter.start(make_spec())
    try:
        wait_for(lambda: adapter.inspect(run_id).status is RunStatus.REVIEW_REQUIRED)

        kinds = event_kinds(adapter, run_id)
        assert EventKind.STEP_FAILED in kinds
        assert kinds[-1] is EventKind.REVIEW_REQUESTED
    finally:
        adapter.dispose(run_id)


def test_error_settle_marks_run_failed_without_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "error_settle")
    adapter = make_adapter(tmp_path)
    run_id = adapter.start(make_spec())
    try:
        wait_for(lambda: adapter.inspect(run_id).status is RunStatus.FAILED)

        events = adapter.events(run_id).events
        assert EventKind.RUN_COMPLETED not in [event.kind for event in events]
        failures = [event for event in events if event.kind is EventKind.STEP_FAILED]
        assert failures
        assert failures[-1].data["will_retry"] is False
        assert failures[-1].data["category"] is ErrorCategory.MODEL
        assert "invalid api key" in failures[-1].data["message"]
        assert adapter.inspect(run_id).status is RunStatus.FAILED
    finally:
        adapter.dispose(run_id)


def test_spawn_failure_raises_internal_error(tmp_path: Path) -> None:
    adapter = PiRuntimeAdapter(
        pi_command=("definitely-not-a-real-pi-binary",),
        session_root=tmp_path / "sessions",
        command_timeout=1.0,
        shutdown_timeout=1.0,
    )
    with pytest.raises(AutoResearchError) as excinfo:
        adapter.start(make_spec())
    assert excinfo.value.failure.code == "pi.spawn_failed"
    assert excinfo.value.failure.category is ErrorCategory.INTERNAL


def test_dispose_stops_a_running_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "busy")
    adapter = make_adapter(tmp_path)
    run_id = adapter.start(make_spec())
    wait_for(lambda: EventKind.STEP_STARTED in event_kinds(adapter, run_id))

    adapter.dispose(run_id)

    with pytest.raises(KeyError, match="unknown run"):
        adapter.events(run_id)
    adapter.dispose(run_id)


def test_unknown_run_raises_key_error(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    with pytest.raises(KeyError, match="unknown run"):
        adapter.inspect("run-missing")
    with pytest.raises(KeyError, match="unknown run"):
        adapter.resume("run-missing")
    with pytest.raises(KeyError, match="unknown run"):
        adapter.cancel("run-missing")
