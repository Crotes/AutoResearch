"""Contract tests for ``workflows/exploration-v1.json``.

The workflow file is a declarative step graph consumed by the deterministic
state machine in :mod:`autoresearch.application.workflow`.  These tests assert
the file's shape and that its gates/checkpoints line up with the state machine,
without introducing a JSON Schema for it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autoresearch.application.workflow import WorkflowAction, WorkflowSnapshot, transition
from autoresearch.domain import ArtifactKind, RunStatus

ROOT = Path(__file__).parents[2]
WORKFLOW_PATH = ROOT / "workflows" / "exploration-v1.json"


def load_workflow() -> dict[str, Any]:
    payload = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    value = doc["steps"]
    assert isinstance(value, list)
    return value


def step_ids(doc: dict[str, Any]) -> list[str]:
    return [step["id"] for step in steps(doc)]


def test_top_level_fields_and_types() -> None:
    doc = load_workflow()

    assert isinstance(doc["id"], str) and doc["id"] == "exploration-v1"
    assert isinstance(doc["version"], int) and doc["version"] == 1
    assert isinstance(doc["workflow_version"], str) and doc["workflow_version"] == "research-v1"
    assert isinstance(doc["name"], str) and doc["name"]
    assert isinstance(doc["steps"], list) and doc["steps"]


def test_step_field_types() -> None:
    for step in steps(load_workflow()):
        assert isinstance(step["id"], str) and step["id"]
        assert isinstance(step["artifact_kind"], (str, type(None)))
        assert isinstance(step["gate"], (str, type(None)))
        assert isinstance(step["checkpoint"], (str, type(None)))


def test_exactly_two_gates_in_order() -> None:
    doc = load_workflow()
    gates = [step for step in steps(doc) if step["gate"] is not None]

    assert [gate["gate"] for gate in gates] == ["source_selection", "final_approval"]
    assert [gate["id"] for gate in gates] == ["select_sources", "approve_final"]

    ids = step_ids(doc)
    assert ids.index("select_sources") < ids.index("approve_final")


def test_exactly_three_checkpoints() -> None:
    doc = load_workflow()
    checkpoints = [step["checkpoint"] for step in steps(doc) if step["checkpoint"] is not None]

    assert checkpoints == ["overviews_ready", "analyses_ready", "completed"]


def test_artifact_producers_use_valid_artifact_kinds_in_order() -> None:
    doc = load_workflow()
    producers = [
        (step["id"], step["artifact_kind"])
        for step in steps(doc)
        if step["artifact_kind"] is not None
    ]

    assert producers == [
        ("collect_sources", "overview"),
        ("analyze_selected", "analysis"),
        ("synthesize", "synthesis"),
    ]
    valid_kinds = {kind.value for kind in ArtifactKind}
    assert {kind for _, kind in producers} <= valid_kinds


def test_each_gate_is_between_artifact_producers() -> None:
    doc = load_workflow()
    ids = step_ids(doc)

    assert (
        ids.index("collect_sources") < ids.index("select_sources") < ids.index("analyze_selected")
    )
    assert ids.index("analyze_selected") < ids.index("approve_final") < ids.index("synthesize")


def test_gate_checkpoints_match_workflow_state_machine() -> None:
    doc = load_workflow()
    gates = {step["id"]: step["checkpoint"] for step in steps(doc) if step["gate"] is not None}
    assert gates == {"select_sources": "overviews_ready", "approve_final": "analyses_ready"}

    # RECORD_SELECTION is only legal once the overview gate is reached.
    selected = transition(
        WorkflowSnapshot(status=RunStatus.REVIEW_REQUIRED, checkpoint=gates["select_sources"]),
        WorkflowAction.RECORD_SELECTION,
    )
    assert selected.status is RunStatus.PAUSED

    # APPROVE_FINAL is only legal once the analysis gate is reached.
    approved = transition(
        WorkflowSnapshot(status=RunStatus.REVIEW_REQUIRED, checkpoint=gates["approve_final"]),
        WorkflowAction.APPROVE_FINAL,
    )
    assert approved.status is RunStatus.PAUSED

    # RESUME past the final gate lands on the terminal checkpoint declared by
    # the workflow file.
    final_checkpoint = steps(doc)[-1]["checkpoint"]
    completed = transition(
        WorkflowSnapshot(
            status=RunStatus.PAUSED,
            checkpoint=gates["approve_final"],
            final_approved=True,
        ),
        WorkflowAction.RESUME,
    )
    assert completed.status is RunStatus.COMPLETED
    assert completed.checkpoint == final_checkpoint == "completed"
