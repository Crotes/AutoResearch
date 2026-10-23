"""Cross-process recovery: a fresh PiRuntimeAdapter takes over a run via restore().

Three adapter instances (each standing in for a separate host process) drive one
run to completion, handing over a RuntimeSnapshot at every review gate. All
instances share one session_root so the audit log accumulates across processes.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from autoresearch.adapters.pi import PiRuntimeAdapter
from autoresearch.domain import EventKind, ResearchPlan, RunSpec, RunStatus, SourceKind
from autoresearch.ports import RuntimeSnapshot

FAKE_PI = Path(__file__).parents[1] / "fake_pi.py"


def make_spec(max_duration_seconds: int = 60) -> RunSpec:
    return RunSpec(
        project_id="project-pi-restore",
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


def make_adapter(
    tmp_path: Path,
    run_env: Callable[[str], dict[str, str]] | None = None,
) -> PiRuntimeAdapter:
    return PiRuntimeAdapter(
        pi_command=(sys.executable, str(FAKE_PI)),
        session_root=tmp_path / "sessions",
        command_timeout=5.0,
        shutdown_timeout=2.0,
        run_env=run_env,
    )


def wait_for(predicate: Callable[[], bool], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met within the timeout")


def take_snapshot(
    adapter: PiRuntimeAdapter,
    run_id: str,
    spec: RunSpec,
    *,
    selected_work_ids: tuple[str, ...] = (),
    final_approved: bool = False,
) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        run=adapter.inspect(run_id),
        spec=spec,
        events=adapter.events(run_id).events,
        selected_work_ids=selected_work_ids,
        final_approved=final_approved,
    )


def test_run_recovers_across_three_adapter_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "happy")
    spec = make_spec()

    adapter1 = make_adapter(tmp_path)
    run_id = adapter1.start(spec)
    wait_for(
        lambda: adapter1.inspect(run_id).status is RunStatus.REVIEW_REQUIRED,
        timeout=2.0,
    )
    snapshot1 = take_snapshot(adapter1, run_id, spec)
    adapter1.dispose(run_id)

    adapter2 = make_adapter(tmp_path)
    adapter2.restore(snapshot1)
    assert adapter2.events(run_id).events == snapshot1.events
    adapter2.review_selection(run_id, ("work-self-refine",))
    adapter2.resume(run_id)
    wait_for(
        lambda: adapter2.inspect(run_id).checkpoint == "analyses_ready",
        timeout=2.0,
    )
    snapshot2 = take_snapshot(adapter2, run_id, spec, selected_work_ids=("work-self-refine",))
    adapter2.dispose(run_id)

    adapter3 = make_adapter(tmp_path)
    try:
        adapter3.restore(snapshot2)
        adapter3.review_final(run_id, approved=True)
        adapter3.resume(run_id)
        run = adapter3.inspect(run_id)
        assert run.status is RunStatus.COMPLETED
        assert run.checkpoint == "completed"

        events = adapter3.events(run_id).events
        assert [event.kind for event in events] == [
            EventKind.RUN_STARTED,
            EventKind.STEP_STARTED,
            EventKind.ARTIFACT_CREATED,
            EventKind.REVIEW_REQUESTED,
            EventKind.STEP_STARTED,
            EventKind.ARTIFACT_CREATED,
            EventKind.REVIEW_REQUESTED,
            EventKind.RUN_COMPLETED,
        ]
        assert [event.sequence for event in events] == list(range(len(events)))
    finally:
        adapter3.dispose(run_id)

    audit = tmp_path / "sessions" / run_id / "pi-events.jsonl"
    audit_records = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    resume_prompts = [
        record
        for record in audit_records
        if record.get("type") == "message_start"
        and "人工已选择以下成果" in str(record.get("message", {}).get("content", ""))
    ]
    assert resume_prompts, "restored process never received the resume prompt"


def test_restore_rejects_a_run_id_that_is_already_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_PI_SCENARIO", "happy")
    spec = make_spec()
    adapter = make_adapter(tmp_path)
    run_id = adapter.start(spec)
    try:
        wait_for(
            lambda: adapter.inspect(run_id).status is RunStatus.REVIEW_REQUIRED,
            timeout=2.0,
        )
        snapshot = take_snapshot(adapter, run_id, spec)
        with pytest.raises(ValueError, match="already active"):
            adapter.restore(snapshot)
    finally:
        adapter.dispose(run_id)


def test_run_env_reaches_both_start_and_restore_processes(tmp_path: Path) -> None:
    dumps = [tmp_path / "env-start.json", tmp_path / "env-restore.json"]
    pending = list(dumps)

    def run_env(run_id: str) -> dict[str, str]:
        return {
            "FAKE_PI_SCENARIO": "happy",
            "FAKE_PI_ENV_DUMP": str(pending.pop(0)),
            "AUTORESEARCH_RUN_ID": run_id,
        }

    spec = make_spec()
    adapter = make_adapter(tmp_path, run_env=run_env)
    run_id = adapter.start(spec)
    wait_for(lambda: dumps[0].exists(), timeout=2.0)
    started_env = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert started_env == {"AUTORESEARCH_RUN_ID": run_id, "PATH_present": True}

    wait_for(
        lambda: adapter.inspect(run_id).status is RunStatus.REVIEW_REQUIRED,
        timeout=2.0,
    )
    snapshot = take_snapshot(adapter, run_id, spec)
    adapter.dispose(run_id)

    adapter2 = make_adapter(tmp_path, run_env=run_env)
    adapter2.restore(snapshot)
    try:
        wait_for(lambda: dumps[1].exists(), timeout=2.0)
        restored_env = json.loads(dumps[1].read_text(encoding="utf-8"))
        assert restored_env == {"AUTORESEARCH_RUN_ID": run_id, "PATH_present": True}
        assert adapter2.inspect(run_id).checkpoint == "overviews_ready"
    finally:
        adapter2.dispose(run_id)
