from __future__ import annotations

import pytest

from autoresearch.application.workflow import (
    InvalidTransitionError,
    WorkflowAction,
    WorkflowSnapshot,
    transition,
)
from autoresearch.domain import RunStatus


def test_selection_gate_cannot_be_bypassed() -> None:
    state = WorkflowSnapshot(
        status=RunStatus.REVIEW_REQUIRED,
        checkpoint="overviews_ready",
    )

    with pytest.raises(InvalidTransitionError, match="human selection"):
        transition(state, WorkflowAction.RESUME)


def test_failed_analysis_preserves_checkpoint_and_can_resume() -> None:
    state = WorkflowSnapshot(
        status=RunStatus.RUNNING,
        checkpoint="overviews_ready",
        has_selection=True,
    )

    failed = transition(state, WorkflowAction.FAIL)
    resumed = transition(failed, WorkflowAction.RESUME)

    assert failed.checkpoint == "overviews_ready"
    assert resumed.status is RunStatus.RUNNING


def test_final_review_gate_completes_only_after_approval() -> None:
    state = WorkflowSnapshot(
        status=RunStatus.REVIEW_REQUIRED,
        checkpoint="analyses_ready",
        has_selection=True,
    )

    with pytest.raises(InvalidTransitionError, match="final human approval"):
        transition(state, WorkflowAction.RESUME)

    approved = transition(state, WorkflowAction.APPROVE_FINAL)
    completed = transition(approved, WorkflowAction.RESUME)

    assert completed.status is RunStatus.COMPLETED
    assert completed.checkpoint == "completed"
