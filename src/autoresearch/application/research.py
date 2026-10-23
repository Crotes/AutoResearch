"""Application service coordinating a recoverable research workflow.

The CLI is a thin input/display layer: this service owns workflow state,
review gates, resume logic, persistence, and export.  Every method rebuilds the
run context from the library so a fresh process (or CLI invocation) can take
over cleanly.  A runtime is created per call and disposed before returning.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from autoresearch.application.export import (
    ExportContentStore,
    ExportLibrary,
    ExportResult,
    export_run,
    run_warnings,
)
from autoresearch.application.workflow import (
    InvalidTransitionError,
    WorkflowAction,
    WorkflowSnapshot,
    transition,
)
from autoresearch.domain.events import DomainEvent, EventKind, EventPage
from autoresearch.domain.library import (
    ResearchProject,
    ReviewDecision,
    ReviewKind,
    ReviewOutcome,
    SkillVersion,
    Work,
)
from autoresearch.domain.models import (
    ArtifactKind,
    ResearchPlan,
    ResearchRun,
    RunSpec,
    RunStatus,
    SourceKind,
)
from autoresearch.ports.runtime import RuntimeSnapshot, WorkerRuntime

_WORKFLOW_VERSION = "research-v1"

_REVIEW_KIND_ORDER = (ReviewKind.PLAN, ReviewKind.SOURCE, ReviewKind.ARTIFACT, ReviewKind.FINAL)

RunPersister = Callable[[ResearchRun, RunSpec], None]


class ResearchLibrary(ExportLibrary, Protocol):
    """Write/read surface the workflow needs from a persistent research library."""

    def save_project(self, project: ResearchProject) -> ResearchProject: ...

    def get_project(self, project_id: str) -> ResearchProject: ...

    def save_work(self, work: Work) -> Work: ...

    def save_run(
        self,
        run: ResearchRun,
        skill_versions: Sequence[SkillVersion] = (),
        *,
        max_duration_seconds: int = 1800,
        max_candidates: int = 20,
    ) -> ResearchRun: ...

    def save_run_spec(self, spec: RunSpec, run_id: str) -> None: ...

    def append_event(self, event: DomainEvent) -> None: ...

    def add_review(self, decision: ReviewDecision) -> ReviewDecision: ...

    def list_reviews(self, run_id: str) -> tuple[ReviewDecision, ...]: ...


@dataclass(frozen=True, slots=True)
class RunStatusView:
    run: ResearchRun
    spec: RunSpec
    artifact_counts: Mapping[ArtifactKind, int]
    stale_artifact_count: int
    latest_reviews: tuple[ReviewDecision, ...]
    warnings: tuple[str, ...]


class ResearchWorkflow:
    """Recoverable research workflow over a persistent library and runtime factory."""

    def __init__(
        self,
        library: ResearchLibrary,
        content_store: ExportContentStore,
        runtime_factory: Callable[[RunPersister], WorkerRuntime],
        *,
        skill_versions: Sequence[SkillVersion] = (),
        workflow_version: str = _WORKFLOW_VERSION,
    ) -> None:
        self._library = library
        self._content_store = content_store
        self._runtime_factory = runtime_factory
        self._skill_versions = tuple(skill_versions)
        self._workflow_version = workflow_version

    def create_project(self, *, name: str, description: str = "") -> ResearchProject:
        project = ResearchProject(
            id=f"project-{uuid4().hex[:12]}", name=name, description=description
        )
        return self._library.save_project(project)

    def start_run(
        self,
        *,
        project_id: str,
        question: str,
        include: Sequence[str],
        exclude: Sequence[str] = (),
        source_kinds: Sequence[SourceKind] = (),
        languages: Sequence[str] = ("zh", "en"),
        max_candidates: int = 20,
        max_duration_seconds: int = 1800,
        start_date: str | None = None,
        end_date: str | None = None,
        seed_urls: Sequence[str] = (),
    ) -> ResearchRun:
        plan = ResearchPlan(
            question=question,
            include_terms=tuple(include),
            exclude_terms=tuple(exclude),
            languages=tuple(languages),
            source_kinds=tuple(source_kinds),
            start_date=start_date,
            end_date=end_date,
            seed_urls=tuple(seed_urls),
        )
        spec = RunSpec(
            project_id=project_id,
            plan=plan,
            workflow_version=self._workflow_version,
            skill_versions={skill.name: skill.version for skill in self._skill_versions},
            max_duration_seconds=max_duration_seconds,
            max_candidates=max_candidates,
        )
        runtime = self._runtime_factory(self._persist_new_run)
        run_id = runtime.start(spec)
        try:
            runtime.wait_for_settlement(run_id, spec.max_duration_seconds + 30.0)
            run = runtime.inspect(run_id)
            self._library.save_run(
                run,
                self._skill_versions,
                max_duration_seconds=spec.max_duration_seconds,
                max_candidates=spec.max_candidates,
            )
            self._library.save_run_spec(spec, run_id)
            self._drain(runtime, run_id)
        finally:
            runtime.dispose(run_id)
        return self._library.get_run(run_id)

    def status(self, run_id: str) -> RunStatusView:
        run = self._library.get_run(run_id)
        spec = self._library.get_run_spec(run_id)
        artifacts = self._library.list_artifacts(run_id)
        everything = self._library.list_artifacts(run_id, include_stale=True)
        counts: dict[ArtifactKind, int] = {kind: 0 for kind in ArtifactKind}
        for artifact in artifacts:
            counts[artifact.submission.kind] = counts[artifact.submission.kind] + 1
        latest: dict[ReviewKind, ReviewDecision] = {}
        for review in self._library.list_reviews(run_id):
            latest[review.kind] = review
        return RunStatusView(
            run=run,
            spec=spec,
            artifact_counts=counts,
            stale_artifact_count=len(everything) - len(artifacts),
            latest_reviews=tuple(latest[kind] for kind in _REVIEW_KIND_ORDER if kind in latest),
            warnings=tuple(run_warnings(self._library, self._content_store, run_id)),
        )

    def events(self, run_id: str, cursor: int = 0) -> EventPage:
        return self._library.list_events(run_id, cursor)

    def record_selection(
        self, run_id: str, *, work_ids: Sequence[str], reviewer: str, comment: str = ""
    ) -> ReviewDecision:
        run = self._library.get_run(run_id)
        updated = transition(self._workflow_snapshot(run_id), WorkflowAction.RECORD_SELECTION)
        decision = ReviewDecision(
            id=f"review-{uuid4().hex}",
            run_id=run_id,
            kind=ReviewKind.SOURCE,
            outcome=ReviewOutcome.APPROVED,
            reviewer=reviewer,
            comment=comment,
            created_at=datetime.now(UTC),
            work_ids=tuple(work_ids),
        )
        self._library.add_review(decision)
        self._persist_run(
            replace(
                run,
                status=updated.status,
                checkpoint=updated.checkpoint,
                updated_at=datetime.now(UTC),
            )
        )
        return decision

    def record_final_review(
        self, run_id: str, *, approved: bool, reviewer: str, comment: str = ""
    ) -> ReviewDecision:
        run = self._library.get_run(run_id)
        if run.status is not RunStatus.REVIEW_REQUIRED or run.checkpoint != "analyses_ready":
            raise InvalidTransitionError("run is not waiting for final review")
        decision = ReviewDecision(
            id=f"review-{uuid4().hex}",
            run_id=run_id,
            kind=ReviewKind.FINAL,
            outcome=ReviewOutcome.APPROVED if approved else ReviewOutcome.CHANGES_REQUESTED,
            reviewer=reviewer,
            comment=comment,
            created_at=datetime.now(UTC),
        )
        self._library.add_review(decision)
        if approved:
            updated = transition(self._workflow_snapshot(run_id), WorkflowAction.APPROVE_FINAL)
            self._persist_run(
                replace(
                    run,
                    status=updated.status,
                    checkpoint=updated.checkpoint,
                    updated_at=datetime.now(UTC),
                )
            )
        return decision

    def resume_run(self, run_id: str) -> ResearchRun:
        transition(self._workflow_snapshot(run_id), WorkflowAction.RESUME)
        snapshot = self._runtime_snapshot(run_id)
        runtime = self._runtime_factory(self._persist_new_run)
        try:
            runtime.restore(snapshot)
            runtime.resume(run_id)
            runtime.wait_for_settlement(run_id, snapshot.spec.max_duration_seconds + 30.0)
            self._drain(runtime, run_id)
            latest = runtime.inspect(run_id)
            self._persist_run(latest)
        finally:
            runtime.dispose(run_id)
        return self._library.get_run(run_id)

    def cancel_run(self, run_id: str) -> ResearchRun:
        run = self._library.get_run(run_id)
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            raise InvalidTransitionError("terminal runs cannot be cancelled")
        self._persist_run(replace(run, status=RunStatus.CANCELLED, updated_at=datetime.now(UTC)))
        return self._library.get_run(run_id)

    def export_run(self, run_id: str, destination: Path) -> ExportResult:
        return export_run(self._library, self._content_store, run_id, destination)

    def _persist_new_run(self, run: ResearchRun, spec: RunSpec) -> None:
        self._library.save_run(
            run,
            self._skill_versions,
            max_duration_seconds=spec.max_duration_seconds,
            max_candidates=spec.max_candidates,
        )
        self._library.save_run_spec(spec, run.id)

    def _persist_run(self, run: ResearchRun) -> None:
        spec = self._library.get_run_spec(run.id)
        self._library.save_run(
            run,
            self._skill_versions,
            max_duration_seconds=spec.max_duration_seconds,
            max_candidates=spec.max_candidates,
        )
        self._library.save_run_spec(spec, run.id)

    def _workflow_snapshot(self, run_id: str) -> WorkflowSnapshot:
        run = self._library.get_run(run_id)
        return WorkflowSnapshot(
            status=run.status,
            checkpoint=run.checkpoint,
            has_selection=bool(self._selected_work_ids(run_id)),
            final_approved=self._final_approved(run_id),
        )

    def _runtime_snapshot(self, run_id: str) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            run=self._library.get_run(run_id),
            spec=self._library.get_run_spec(run_id),
            events=tuple(self._all_events(run_id)),
            selected_work_ids=self._selected_work_ids(run_id),
            final_approved=self._final_approved(run_id),
        )

    def _selected_work_ids(self, run_id: str) -> tuple[str, ...]:
        for review in reversed(self._library.list_reviews(run_id)):
            if review.kind is ReviewKind.SOURCE and review.outcome is ReviewOutcome.APPROVED:
                return review.work_ids
        return ()

    def _final_approved(self, run_id: str) -> bool:
        return any(
            review.kind is ReviewKind.FINAL and review.outcome is ReviewOutcome.APPROVED
            for review in self._library.list_reviews(run_id)
        )

    def _all_events(self, run_id: str) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        cursor = 0
        while True:
            page = self._library.list_events(run_id, cursor)
            events.extend(page.events)
            if not page.events or page.next_cursor <= cursor:
                return events
            cursor = page.next_cursor

    def _drain(self, runtime: WorkerRuntime, run_id: str) -> None:
        cursor = 0
        while True:
            page = runtime.events(run_id, cursor)
            for event in page.events:
                self._append_event(event)
            if not page.events or page.next_cursor <= cursor:
                return
            cursor = page.next_cursor

    def _append_event(self, event: DomainEvent) -> None:
        self._library.append_event(event)
        if event.kind is EventKind.SOURCE_DISCOVERED:
            work_id = event.data.get("work_id")
            if isinstance(work_id, str) and work_id:
                title = event.data.get("title")
                self._library.save_work(
                    Work(id=work_id, title=title if isinstance(title, str) else work_id)
                )
