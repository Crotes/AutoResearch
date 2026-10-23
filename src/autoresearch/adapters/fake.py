"""Deterministic in-memory adapters used by the first vertical slice."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from autoresearch.application.workflow import WorkflowAction, WorkflowSnapshot, transition
from autoresearch.domain.events import DomainEvent, EventKind, EventPage
from autoresearch.domain.models import (
    AccessPolicy,
    Artifact,
    ArtifactKind,
    ArtifactSubmission,
    Candidate,
    ResearchPlan,
    ResearchRun,
    RunSpec,
    RunStatus,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
)
from autoresearch.ports.runtime import RuntimeSnapshot

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemorySourceAdapter:
    """Return a small, fixed corpus without network access."""

    def __init__(self, clock: Clock = _utc_now) -> None:
        self._clock = clock
        self._records = {
            "arxiv:2401.00001": {
                "work_id": "work-self-refine",
                "title": "Self-Refining Language Agents",
                "url": "https://arxiv.org/abs/2401.00001",
                "kind": SourceKind.ARXIV,
                "license": "CC-BY-4.0",
                "text": (
                    "The agent reviews failed trajectories and rewrites its policy. "
                    "Across three tasks, reflection improves success while adding inference cost."
                ),
            },
            "github:lab/evolving-agent": {
                "work_id": "work-evolving-agent",
                "title": "Evolving Agent Toolkit",
                "url": "https://github.com/example/evolving-agent",
                "kind": SourceKind.GITHUB,
                "license": "Apache-2.0",
                "text": (
                    "A reproducible toolkit for mutation, evaluation, and selection "
                    "of agent skills. "
                    "The repository includes fixed benchmarks and ablation scripts."
                ),
            },
            "rss:lab-notes/adaptive-memory": {
                "work_id": "work-adaptive-memory",
                "title": "Adaptive Memory for Long-Lived Agents",
                "url": "https://example.org/blog/adaptive-memory",
                "kind": SourceKind.RSS,
                "license": "CC-BY-4.0",
                "text": (
                    "The article proposes pruning and consolidating memories using task feedback. "
                    "Evidence is preliminary and no evaluation code is available."
                ),
            },
        }

    def discover(self, plan: ResearchPlan) -> Iterable[Candidate]:
        allowed = set(plan.source_kinds)
        for locator, record in self._records.items():
            if allowed and record["kind"] not in allowed:
                continue
            yield Candidate(
                source_ref=SourceRef(kind=cast(SourceKind, record["kind"]), locator=locator),
                title=str(record["title"]),
                canonical_url=str(record["url"]),
                metadata={"work_id": record["work_id"]},
            )

    def materialize(self, source_ref: SourceRef) -> SourceDocument:
        try:
            record = self._records[source_ref.locator]
        except KeyError as error:
            raise KeyError(f"unknown fake source: {source_ref.locator}") from error
        text = str(record["text"])
        digest = hashlib.sha256(text.encode()).hexdigest()
        version = SourceVersion(
            id=f"source-{digest[:12]}",
            work_id=str(record["work_id"]),
            source_ref=source_ref,
            canonical_url=str(record["url"]),
            retrieved_at=self._clock(),
            content_hash=digest,
            access_policy=AccessPolicy.PERSIST,
            license=str(record["license"]),
        )
        return SourceDocument(
            source_version=version,
            media_type="text/plain",
            text=text,
            chunks=(text,),
        )


class InMemoryArtifactStore:
    """Append immutable artifacts and assign monotonically increasing versions."""

    def __init__(self, clock: Clock = _utc_now) -> None:
        self._clock = clock
        self._by_run: dict[str, list[Artifact]] = {}

    def submit(self, run_id: str, submission: ArtifactSubmission) -> Artifact:
        existing = self._by_run.setdefault(run_id, [])
        version = 1 + sum(
            artifact.submission.kind is submission.kind
            and artifact.submission.work_id == submission.work_id
            for artifact in existing
        )
        artifact = Artifact(
            id=f"artifact-{uuid4().hex}",
            run_id=run_id,
            version=version,
            created_at=self._clock(),
            submission=submission,
        )
        existing.append(artifact)
        return artifact

    def list(self, run_id: str) -> tuple[Artifact, ...]:
        return tuple(self._by_run.get(run_id, ()))


class FakeRuntimeAdapter:
    """Run the whole PoC workflow deterministically in memory.

    The adapter intentionally pauses at both human-review gates. ``fail_once_at`` is
    a test seam that simulates an interruption after the last saved checkpoint.
    """

    def __init__(
        self,
        sources: InMemorySourceAdapter | None = None,
        artifacts: InMemoryArtifactStore | None = None,
        *,
        clock: Clock = _utc_now,
        fail_once_at: str | None = None,
    ) -> None:
        self.sources = sources or InMemorySourceAdapter(clock)
        self.artifacts = artifacts or InMemoryArtifactStore(clock)
        self._clock = clock
        self._fail_once_at = fail_once_at
        self._failed_once = False
        self._runs: dict[str, ResearchRun] = {}
        self._specs: dict[str, RunSpec] = {}
        self._events: dict[str, list[DomainEvent]] = {}
        self._documents: dict[str, dict[str, SourceDocument]] = {}
        self._selected: dict[str, tuple[str, ...]] = {}
        self._final_approved: set[str] = set()

    def start(self, spec: RunSpec) -> str:
        run_id = f"run-{uuid4().hex[:12]}"
        now = self._clock()
        self._runs[run_id] = ResearchRun(
            id=run_id,
            project_id=spec.project_id,
            status=RunStatus.RUNNING,
            plan=spec.plan,
            workflow_version=spec.workflow_version,
            created_at=now,
            updated_at=now,
        )
        self._specs[run_id] = spec
        self._events[run_id] = []
        self._documents[run_id] = {}
        self._emit(run_id, EventKind.RUN_STARTED, {"workflow_version": spec.workflow_version})
        self._collect_and_overview(run_id)
        return run_id

    def restore(self, snapshot: RuntimeSnapshot) -> None:
        run_id = snapshot.run.id
        if run_id in self._runs:
            raise ValueError(f"run already active: {run_id}")
        self._runs[run_id] = snapshot.run
        self._specs[run_id] = snapshot.spec
        self._events[run_id] = list(snapshot.events)
        self._documents[run_id] = {}
        self._selected[run_id] = snapshot.selected_work_ids
        if snapshot.final_approved:
            self._final_approved.add(run_id)
        for candidate in list(self.sources.discover(snapshot.spec.plan))[
            : snapshot.spec.max_candidates
        ]:
            document = self.sources.materialize(candidate.source_ref)
            self._documents[run_id][str(candidate.metadata["work_id"])] = document

    def events(self, run_id: str, cursor: int = 0) -> EventPage:
        events = self._require_events(run_id)
        if cursor < 0 or cursor > len(events):
            raise ValueError("event cursor is outside the event stream")
        return EventPage(events=tuple(events[cursor:]), next_cursor=len(events))

    def cancel(self, run_id: str) -> None:
        run = self.inspect(run_id)
        updated = transition(self._snapshot(run_id), WorkflowAction.CANCEL)
        if updated.status is run.status:
            return
        self._apply_snapshot(run_id, updated)
        self._emit(run_id, EventKind.RUN_CANCELLED, {"checkpoint": run.checkpoint})

    def resume(self, run_id: str) -> None:
        run = self.inspect(run_id)
        if run.status is RunStatus.COMPLETED:
            return
        updated = transition(self._snapshot(run_id), WorkflowAction.RESUME)
        self._apply_snapshot(run_id, updated)
        if run.checkpoint == "overviews_ready":
            self._analyze_and_synthesize(run_id)
            return
        if run.checkpoint == "analyses_ready":
            self._emit(run_id, EventKind.RUN_COMPLETED, {})
            return

    def inspect(self, run_id: str) -> ResearchRun:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise KeyError(f"unknown run: {run_id}") from error

    def wait_for_settlement(self, run_id: str, timeout: float) -> None:
        self.inspect(run_id)

    def dispose(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
        self._specs.pop(run_id, None)
        self._events.pop(run_id, None)
        self._documents.pop(run_id, None)
        self._selected.pop(run_id, None)
        self._final_approved.discard(run_id)

    def review_selection(self, run_id: str, work_ids: Iterable[str]) -> None:
        run = self.inspect(run_id)
        if run.status is not RunStatus.REVIEW_REQUIRED or run.checkpoint != "overviews_ready":
            raise ValueError("run is not waiting for source selection")
        selected = tuple(dict.fromkeys(work_ids))
        known = set(self._documents[run_id])
        if not selected:
            raise ValueError("select at least one work")
        if unknown := set(selected) - known:
            raise ValueError(f"unknown work ids: {sorted(unknown)}")
        self._selected[run_id] = selected
        self._apply_snapshot(
            run_id,
            transition(self._snapshot(run_id), WorkflowAction.RECORD_SELECTION),
        )

    def review_final(self, run_id: str, *, approved: bool) -> None:
        run = self.inspect(run_id)
        if run.status is not RunStatus.REVIEW_REQUIRED or run.checkpoint != "analyses_ready":
            raise ValueError("run is not waiting for final review")
        if not approved:
            raise ValueError("the fake slice only supports approval; cancel to reject")
        self._final_approved.add(run_id)
        self._apply_snapshot(
            run_id,
            transition(self._snapshot(run_id), WorkflowAction.APPROVE_FINAL),
        )

    def list_artifacts(self, run_id: str) -> tuple[Artifact, ...]:
        self.inspect(run_id)
        return self.artifacts.list(run_id)

    def export(self, run_id: str, destination: Path) -> Path:
        run = self.inspect(run_id)
        destination.mkdir(parents=True, exist_ok=True)
        artifacts_root = destination / "artifacts"
        (artifacts_root / "overviews").mkdir(parents=True, exist_ok=True)
        (artifacts_root / "analyses").mkdir(parents=True, exist_ok=True)
        (destination / "sources").mkdir(parents=True, exist_ok=True)

        self._write_json(destination / "run.json", self._serialize_run(run))
        with (destination / "events.jsonl").open("w", encoding="utf-8") as handle:
            for event in self._events[run_id]:
                handle.write(json.dumps(self._serialize_event(event), ensure_ascii=False) + "\n")

        exported: list[dict[str, Any]] = []
        for work_id, document in self._documents[run_id].items():
            (destination / "sources" / f"{work_id}.md").write_text(document.text, encoding="utf-8")
        for artifact in self.artifacts.list(run_id):
            path = self._artifact_path(artifacts_root, artifact)
            path.write_text(artifact.submission.markdown, encoding="utf-8")
            structured_path = path.with_suffix(".json")
            self._write_json(structured_path, self._serialize_artifact(artifact))
            exported.append(
                {
                    "id": artifact.id,
                    "kind": artifact.submission.kind,
                    "path": path.relative_to(destination).as_posix(),
                }
            )

        self._write_json(
            destination / "manifest.json",
            {
                "format_version": "1",
                "run_id": run_id,
                "status": run.status,
                "artifacts": exported,
            },
        )
        return destination

    def _collect_and_overview(self, run_id: str) -> None:
        self._emit(run_id, EventKind.STEP_STARTED, {"step": "collect_sources"})
        spec = self._specs[run_id]
        for candidate in list(self.sources.discover(spec.plan))[: spec.max_candidates]:
            work_id = str(candidate.metadata["work_id"])
            self._emit(
                run_id,
                EventKind.SOURCE_DISCOVERED,
                {"work_id": work_id, "title": candidate.title, "url": candidate.canonical_url},
            )
            document = self.sources.materialize(candidate.source_ref)
            self._documents[run_id][work_id] = document
            self._emit(
                run_id,
                EventKind.SOURCE_MATERIALIZED,
                {"work_id": work_id, "source_version_id": document.source_version.id},
            )
            overview = self._make_overview(work_id, candidate, document)
            artifact = self.artifacts.submit(run_id, overview)
            self._emit_artifact(run_id, artifact)
        self._apply_snapshot(
            run_id,
            transition(self._snapshot(run_id), WorkflowAction.OVERVIEWS_READY),
        )
        self._emit(
            run_id,
            EventKind.REVIEW_REQUESTED,
            {"gate": "source_selection", "candidate_count": len(self._documents[run_id])},
        )

    def _analyze_and_synthesize(self, run_id: str) -> None:
        self._emit(run_id, EventKind.STEP_STARTED, {"step": "analyze_selected"})
        try:
            self._maybe_fail("analyze_selected")
            for work_id in self._selected[run_id]:
                document = self._documents[run_id][work_id]
                artifact = self.artifacts.submit(run_id, self._make_analysis(work_id, document))
                self._emit_artifact(run_id, artifact)
            synthesis = self.artifacts.submit(
                run_id, self._make_synthesis(run_id, self._selected[run_id])
            )
            self._emit_artifact(run_id, synthesis)
        except RuntimeError as error:
            self._apply_snapshot(
                run_id,
                transition(self._snapshot(run_id), WorkflowAction.FAIL),
            )
            self._emit(
                run_id,
                EventKind.STEP_FAILED,
                {"step": "analyze_selected", "category": "internal", "message": str(error)},
            )
            return
        self._apply_snapshot(
            run_id,
            transition(self._snapshot(run_id), WorkflowAction.ANALYSES_READY),
        )
        self._emit(run_id, EventKind.REVIEW_REQUESTED, {"gate": "final_approval"})

    def _make_overview(
        self, work_id: str, candidate: Candidate, document: SourceDocument
    ) -> ArtifactSubmission:
        conclusion = document.chunks[0].split(". ", maxsplit=1)[0] + "."
        return ArtifactSubmission(
            kind=ArtifactKind.OVERVIEW,
            work_id=work_id,
            markdown=(
                f"# {candidate.title}\n\n{conclusion}\n\n"
                f"- 来源: {candidate.canonical_url}\n- 标签: Agent 自进化\n"
            ),
            structured={"conclusion": conclusion, "relevance": 0.9, "title": candidate.title},
            evidence_ids=(f"{document.source_version.id}#chunk-1",),
            warnings=(),
            skill_name="triage-sources",
            skill_version="fake-0.1.0",
        )

    def _make_analysis(self, work_id: str, document: SourceDocument) -> ArtifactSubmission:
        evidence = f"{document.source_version.id}#chunk-1"
        return ArtifactSubmission(
            kind=ArtifactKind.ANALYSIS,
            work_id=work_id,
            markdown=(
                f"# 详细解读: {work_id}\n\n"
                f"## 方法与结果\n\n{document.text}\n\n"
                f"## 证据\n\n- `{evidence}`\n"
            ),
            structured={"method": document.text, "limitations": "固定样例, 仅验证流程。"},
            evidence_ids=(evidence,),
            warnings=("这是 Fake Adapter 生成的固定解读。",),
            skill_name="analyze-source",
            skill_version="fake-0.1.0",
        )

    def _make_synthesis(self, run_id: str, work_ids: tuple[str, ...]) -> ArtifactSubmission:
        evidence = tuple(
            f"{self._documents[run_id][work_id].source_version.id}#chunk-1" for work_id in work_ids
        )
        joined = "、".join(work_ids)
        return ArtifactSubmission(
            kind=ArtifactKind.SYNTHESIS,
            work_id=None,
            markdown=(
                "# 分类总结\n\n"
                "## 方法谱系\n\n当前样例覆盖反思式改进、技能演化与记忆适应。\n\n"
                f"## 纳入成果\n\n{joined}\n"
            ),
            structured={"categories": ["反思", "演化", "记忆"], "work_ids": list(work_ids)},
            evidence_ids=evidence,
            warnings=("固定样例不代表真实研究结论。",),
            skill_name="synthesize-topic",
            skill_version="fake-0.1.0",
        )

    def _emit_artifact(self, run_id: str, artifact: Artifact) -> None:
        self._emit(
            run_id,
            EventKind.ARTIFACT_CREATED,
            {
                "artifact_id": artifact.id,
                "kind": artifact.submission.kind,
                "work_id": artifact.submission.work_id,
            },
        )

    def _emit(self, run_id: str, kind: EventKind, data: dict[str, Any]) -> None:
        events = self._require_events(run_id)
        events.append(
            DomainEvent(
                id=f"event-{uuid4().hex}",
                run_id=run_id,
                sequence=len(events),
                kind=kind,
                occurred_at=self._clock(),
                data=data,
            )
        )

    def _update(self, run_id: str, *, status: RunStatus, checkpoint: str | None = None) -> None:
        run = self.inspect(run_id)
        self._runs[run_id] = replace(
            run,
            status=status,
            checkpoint=run.checkpoint if checkpoint is None else checkpoint,
            updated_at=self._clock(),
        )

    def _snapshot(self, run_id: str) -> WorkflowSnapshot:
        run = self.inspect(run_id)
        return WorkflowSnapshot(
            status=run.status,
            checkpoint=run.checkpoint,
            has_selection=bool(self._selected.get(run_id)),
            final_approved=run_id in self._final_approved,
        )

    def _apply_snapshot(self, run_id: str, snapshot: WorkflowSnapshot) -> None:
        self._update(run_id, status=snapshot.status, checkpoint=snapshot.checkpoint)

    def _maybe_fail(self, step: str) -> None:
        if self._fail_once_at == step and not self._failed_once:
            self._failed_once = True
            raise RuntimeError("simulated worker interruption")

    def _require_events(self, run_id: str) -> list[DomainEvent]:
        try:
            return self._events[run_id]
        except KeyError as error:
            raise KeyError(f"unknown run: {run_id}") from error

    @staticmethod
    def _artifact_path(root: Path, artifact: Artifact) -> Path:
        submission = artifact.submission
        if submission.kind is ArtifactKind.SYNTHESIS:
            return root / "synthesis.md"
        directory = "overviews" if submission.kind is ArtifactKind.OVERVIEW else "analyses"
        return root / directory / f"{submission.work_id}.md"

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _serialize_run(run: ResearchRun) -> dict[str, Any]:
        value = asdict(run)
        value["status"] = run.status
        value["created_at"] = run.created_at.isoformat()
        value["updated_at"] = run.updated_at.isoformat()
        value["plan"]["source_kinds"] = list(run.plan.source_kinds)
        return value

    @staticmethod
    def _serialize_event(event: DomainEvent) -> dict[str, Any]:
        return {
            "id": event.id,
            "run_id": event.run_id,
            "sequence": event.sequence,
            "kind": event.kind,
            "occurred_at": event.occurred_at.isoformat(),
            "data": event.data,
        }

    @staticmethod
    def _serialize_artifact(artifact: Artifact) -> dict[str, Any]:
        submission = artifact.submission
        return {
            "id": artifact.id,
            "run_id": artifact.run_id,
            "version": artifact.version,
            "created_at": artifact.created_at.isoformat(),
            "kind": submission.kind,
            "work_id": submission.work_id,
            "markdown": submission.markdown,
            "structured": submission.structured,
            "evidence_ids": list(submission.evidence_ids),
            "warnings": list(submission.warnings),
            "skill": {"name": submission.skill_name, "version": submission.skill_version},
        }
