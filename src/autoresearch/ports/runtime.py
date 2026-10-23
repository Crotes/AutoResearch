"""Runtime seam hiding Pi RPC and process lifecycle details."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from autoresearch.domain.events import DomainEvent, EventPage
from autoresearch.domain.models import ResearchRun, RunSpec


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """State a fresh WorkerRuntime needs to take over a run in a new process."""

    run: ResearchRun
    spec: RunSpec
    events: tuple[DomainEvent, ...]
    selected_work_ids: tuple[str, ...]
    final_approved: bool


@runtime_checkable
class WorkerRuntime(Protocol):
    def start(self, spec: RunSpec) -> str: ...

    def events(self, run_id: str, cursor: int = 0) -> EventPage: ...

    def cancel(self, run_id: str) -> None: ...

    def resume(self, run_id: str) -> None: ...

    def inspect(self, run_id: str) -> ResearchRun: ...

    def dispose(self, run_id: str) -> None: ...

    def restore(self, snapshot: RuntimeSnapshot) -> None: ...

    def wait_for_settlement(self, run_id: str, timeout: float) -> None: ...
