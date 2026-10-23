"""A fresh FakeRuntimeAdapter must be able to take over a run from a snapshot."""

from __future__ import annotations

import pytest

from autoresearch.adapters.fake import FakeRuntimeAdapter
from autoresearch.domain import EventKind, ResearchPlan, RunSpec, RunStatus
from autoresearch.ports import RuntimeSnapshot


def make_spec() -> RunSpec:
    return RunSpec(
        project_id="project-restore",
        plan=ResearchPlan(
            question="Agent 如何自进化?",
            include_terms=("agent self-evolution",),
            source_kinds=(),
        ),
        workflow_version="fake-0.1.0",
        skill_versions={},
        max_duration_seconds=3600,
        max_candidates=5,
    )


def take_snapshot(
    adapter: FakeRuntimeAdapter,
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


def test_restore_continues_a_paused_run_to_completion() -> None:
    spec = make_spec()
    adapter1 = FakeRuntimeAdapter()
    run_id = adapter1.start(spec)
    run = adapter1.inspect(run_id)
    assert run.status is RunStatus.REVIEW_REQUIRED
    assert run.checkpoint == "overviews_ready"

    snapshot = take_snapshot(adapter1, run_id, spec)
    adapter1.dispose(run_id)

    adapter2 = FakeRuntimeAdapter()
    adapter2.restore(snapshot)
    assert adapter2.inspect(run_id) == snapshot.run
    assert adapter2.events(run_id).events == snapshot.events

    adapter2.review_selection(run_id, ("work-self-refine",))
    adapter2.resume(run_id)
    run = adapter2.inspect(run_id)
    assert run.status is RunStatus.REVIEW_REQUIRED
    assert run.checkpoint == "analyses_ready"

    adapter2.review_final(run_id, approved=True)
    adapter2.resume(run_id)
    run = adapter2.inspect(run_id)
    assert run.status is RunStatus.COMPLETED
    assert run.checkpoint == "completed"

    events = adapter2.events(run_id).events
    assert [event.sequence for event in events] == list(range(len(events)))
    assert events[-1].kind is EventKind.RUN_COMPLETED


def test_restore_rebuilds_documents_so_known_work_ids_are_accepted() -> None:
    spec = make_spec()
    adapter1 = FakeRuntimeAdapter()
    run_id = adapter1.start(spec)
    snapshot = take_snapshot(adapter1, run_id, spec)
    adapter1.dispose(run_id)

    adapter2 = FakeRuntimeAdapter()
    adapter2.restore(snapshot)
    adapter2.review_selection(run_id, ("work-evolving-agent", "work-adaptive-memory"))
    adapter2.resume(run_id)

    assert adapter2.inspect(run_id).checkpoint == "analyses_ready"


def test_restore_of_a_terminal_run_is_a_no_op_takeover() -> None:
    spec = make_spec()
    adapter1 = FakeRuntimeAdapter()
    run_id = adapter1.start(spec)
    adapter1.review_selection(run_id, ("work-self-refine",))
    adapter1.resume(run_id)
    adapter1.review_final(run_id, approved=True)
    adapter1.resume(run_id)
    assert adapter1.inspect(run_id).status is RunStatus.COMPLETED

    snapshot = take_snapshot(adapter1, run_id, spec, final_approved=True)
    adapter1.dispose(run_id)

    adapter2 = FakeRuntimeAdapter()
    adapter2.restore(snapshot)
    assert adapter2.inspect(run_id).status is RunStatus.COMPLETED
    event_count = len(adapter2.events(run_id).events)
    adapter2.resume(run_id)
    assert len(adapter2.events(run_id).events) == event_count


def test_restore_rejects_a_run_id_that_is_already_active() -> None:
    spec = make_spec()
    adapter = FakeRuntimeAdapter()
    run_id = adapter.start(spec)
    snapshot = take_snapshot(adapter, run_id, spec)

    with pytest.raises(ValueError, match="already active"):
        adapter.restore(snapshot)
