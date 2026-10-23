from __future__ import annotations

from collections.abc import Iterable

from autoresearch.domain import (
    Artifact,
    ArtifactSubmission,
    Candidate,
    EventPage,
    ResearchPlan,
    ResearchRun,
    RunSpec,
    SourceDocument,
    SourceRef,
)
from autoresearch.ports import (
    ArtifactSubmissionPort,
    RuntimeSnapshot,
    SourceAcquisition,
    WorkerRuntime,
)


class FakeRuntime:
    def start(self, spec: RunSpec) -> str:
        return "run-1"

    def events(self, run_id: str, cursor: int = 0) -> EventPage:
        return EventPage(events=(), next_cursor=cursor)

    def cancel(self, run_id: str) -> None:
        return None

    def resume(self, run_id: str) -> None:
        return None

    def restore(self, snapshot: RuntimeSnapshot) -> None:
        return None

    def wait_for_settlement(self, run_id: str, timeout: float) -> None:
        return None

    def inspect(self, run_id: str) -> ResearchRun:
        raise NotImplementedError

    def dispose(self, run_id: str) -> None:
        return None


class FakeSources:
    def discover(self, plan: ResearchPlan) -> Iterable[Candidate]:
        return ()

    def materialize(self, source_ref: SourceRef) -> SourceDocument:
        raise NotImplementedError


class FakeArtifacts:
    def submit(self, run_id: str, submission: ArtifactSubmission) -> Artifact:
        raise NotImplementedError


def test_fakes_satisfy_runtime_checkable_ports() -> None:
    assert isinstance(FakeRuntime(), WorkerRuntime)
    assert isinstance(FakeSources(), SourceAcquisition)
    assert isinstance(FakeArtifacts(), ArtifactSubmissionPort)
