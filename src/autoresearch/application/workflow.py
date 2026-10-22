"""Pure state machine for workflow checkpoints and human-review gates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from autoresearch.domain.models import RunStatus


class InvalidTransitionError(ValueError):
    """Raised when an action would bypass a workflow invariant."""


class WorkflowAction(StrEnum):
    OVERVIEWS_READY = "overviews_ready"
    RECORD_SELECTION = "record_selection"
    RESUME = "resume"
    ANALYSES_READY = "analyses_ready"
    APPROVE_FINAL = "approve_final"
    FAIL = "fail"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class WorkflowSnapshot:
    status: RunStatus
    checkpoint: str | None
    has_selection: bool = False
    final_approved: bool = False


def transition(state: WorkflowSnapshot, action: WorkflowAction) -> WorkflowSnapshot:
    """Apply one legal action while preserving both mandatory review gates."""
    if action is WorkflowAction.CANCEL:
        if state.status in {RunStatus.COMPLETED, RunStatus.CANCELLED}:
            return state
        return replace(state, status=RunStatus.CANCELLED)

    if state.status is RunStatus.CANCELLED:
        raise InvalidTransitionError("cancelled runs cannot transition")
    if state.status is RunStatus.COMPLETED:
        raise InvalidTransitionError("completed runs cannot transition")

    if action is WorkflowAction.OVERVIEWS_READY:
        if state.status is not RunStatus.RUNNING or state.checkpoint is not None:
            raise InvalidTransitionError("overviews can only finish during initial collection")
        return replace(
            state,
            status=RunStatus.REVIEW_REQUIRED,
            checkpoint="overviews_ready",
        )

    if action is WorkflowAction.RECORD_SELECTION:
        if state.status is not RunStatus.REVIEW_REQUIRED or state.checkpoint != "overviews_ready":
            raise InvalidTransitionError("run is not waiting for source selection")
        return replace(state, status=RunStatus.PAUSED, has_selection=True)

    if action is WorkflowAction.RESUME:
        if state.checkpoint == "overviews_ready":
            if not state.has_selection:
                raise InvalidTransitionError("a human selection is required before analysis")
            if state.status not in {RunStatus.PAUSED, RunStatus.FAILED}:
                raise InvalidTransitionError("run is not paused or failed")
            return replace(state, status=RunStatus.RUNNING)
        if state.checkpoint == "analyses_ready":
            if not state.final_approved:
                raise InvalidTransitionError("final human approval is required before completion")
            if state.status is not RunStatus.PAUSED:
                raise InvalidTransitionError("run is not paused after final review")
            return replace(state, status=RunStatus.COMPLETED, checkpoint="completed")
        raise InvalidTransitionError(f"run cannot resume from checkpoint: {state.checkpoint!r}")

    if action is WorkflowAction.ANALYSES_READY:
        if state.status is not RunStatus.RUNNING or state.checkpoint != "overviews_ready":
            raise InvalidTransitionError("analysis can only finish after selection")
        return replace(
            state,
            status=RunStatus.REVIEW_REQUIRED,
            checkpoint="analyses_ready",
        )

    if action is WorkflowAction.APPROVE_FINAL:
        if state.status is not RunStatus.REVIEW_REQUIRED or state.checkpoint != "analyses_ready":
            raise InvalidTransitionError("run is not waiting for final review")
        return replace(state, status=RunStatus.PAUSED, final_approved=True)

    if action is WorkflowAction.FAIL:
        if state.status is not RunStatus.RUNNING:
            raise InvalidTransitionError("only a running step can fail")
        return replace(state, status=RunStatus.FAILED)

    raise InvalidTransitionError(f"unsupported workflow action: {action}")
