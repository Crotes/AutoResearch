"""Runtime-independent domain events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EventKind(StrEnum):
    RUN_STARTED = "run.started"
    STEP_STARTED = "step.started"
    SOURCE_DISCOVERED = "source.discovered"
    SOURCE_MATERIALIZED = "source.materialized"
    ARTIFACT_CREATED = "artifact.created"
    REVIEW_REQUESTED = "review.requested"
    STEP_FAILED = "step.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_COMPLETED = "run.completed"


@dataclass(frozen=True, slots=True)
class DomainEvent:
    id: str
    run_id: str
    sequence: int
    kind: EventKind
    occurred_at: datetime
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("event sequence must be non-negative")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must include a timezone")


@dataclass(frozen=True, slots=True)
class EventPage:
    events: tuple[DomainEvent, ...]
    next_cursor: int

    def __post_init__(self) -> None:
        if self.next_cursor < 0:
            raise ValueError("event cursor must be non-negative")
