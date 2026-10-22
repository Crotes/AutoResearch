"""Runtime seam hiding Pi RPC and process lifecycle details."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from autoresearch.domain.events import EventPage
from autoresearch.domain.models import ResearchRun, RunSpec


@runtime_checkable
class WorkerRuntime(Protocol):
    def start(self, spec: RunSpec) -> str: ...

    def events(self, run_id: str, cursor: int = 0) -> EventPage: ...

    def cancel(self, run_id: str) -> None: ...

    def resume(self, run_id: str) -> None: ...

    def inspect(self, run_id: str) -> ResearchRun: ...

    def dispose(self, run_id: str) -> None: ...
