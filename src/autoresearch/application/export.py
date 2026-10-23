"""Generic run export: dump run metadata, artifacts, events, and evidence to a directory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from autoresearch.domain.events import DomainEvent, EventKind, EventPage
from autoresearch.domain.library import Work
from autoresearch.domain.models import (
    AccessPolicy,
    Artifact,
    ArtifactKind,
    ResearchRun,
    RunSpec,
    SourceVersion,
)

_FORMAT_VERSION = "1"
_FILENAME_LIMIT = 80
_EVIDENCE_ANCHOR = re.compile(r"^(?P<source>[^#]+)#chunk-\d+(?:@page-\d+)?$")


class ExportLibrary(Protocol):
    """Narrow read surface the exporter needs from a research library."""

    def get_run(self, run_id: str) -> ResearchRun: ...

    def get_run_spec(self, run_id: str) -> RunSpec: ...

    def list_artifacts(
        self, run_id: str, *, include_stale: bool = False
    ) -> tuple[Artifact, ...]: ...

    def list_events(self, run_id: str, cursor: int = 0) -> EventPage: ...

    def list_run_sources(self, run_id: str) -> tuple[str, ...]: ...

    def get_source(self, source_version_id: str) -> SourceVersion: ...

    def get_work(self, work_id: str) -> Work: ...


class ExportContentStore(Protocol):
    """Narrow read surface the exporter needs from a content store."""

    def get(self, digest: str) -> str: ...


@dataclass(frozen=True, slots=True)
class ExportResult:
    destination: Path
    manifest_path: Path
    artifact_count: int
    stale_artifact_count: int
    warnings: tuple[str, ...]


def export_run(
    library: ExportLibrary,
    content_store: ExportContentStore,
    run_id: str,
    destination: str | Path,
) -> ExportResult:
    """Export one run into ``destination`` as JSON/JSONL/Markdown files.

    Re-exporting into the same destination overwrites the previous bundle.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    run = library.get_run(run_id)
    spec = library.get_run_spec(run_id)
    active = list(library.list_artifacts(run_id))
    everything = list(library.list_artifacts(run_id, include_stale=True))
    active_ids = {artifact.id for artifact in active}
    stale = [artifact for artifact in everything if artifact.id not in active_ids]
    events = _all_events(library, run_id)

    artifact_entries = _write_artifacts(library, destination, active)
    stale_entries = [
        {
            "id": artifact.id,
            "kind": str(artifact.submission.kind),
            "work_id": artifact.submission.work_id,
            "version": artifact.version,
            "validity": "stale",
            "reason": None,
        }
        for artifact in stale
    ]
    warnings = run_warnings(library, content_store, run_id)
    if stale:
        warnings.insert(0, f"导出包含 {len(stale)} 个已失效工件 (stale)")

    _write_json(destination / "run.json", _run_payload(run, spec))
    _write_events(destination / "events.jsonl", events)
    evidence_index, _ = _evidence_index(library, content_store, run_id)
    _write_json(destination / "evidence" / "index.json", evidence_index)

    manifest = {
        "format_version": _FORMAT_VERSION,
        "run_id": run_id,
        "counts": {
            "artifacts": len(artifact_entries),
            "stale_artifacts": len(stale_entries),
            "events": len(events),
            "sources": len(evidence_index),
        },
        "artifacts": artifact_entries,
        "stale_artifacts": stale_entries,
        "evidence_index": "evidence/index.json",
        "warnings_file": "warnings.md",
    }
    manifest_path = destination / "manifest.json"
    _write_json(manifest_path, manifest)
    _write_warnings(destination / "warnings.md", warnings)

    return ExportResult(
        destination=destination,
        manifest_path=manifest_path,
        artifact_count=len(artifact_entries),
        stale_artifact_count=len(stale_entries),
        warnings=tuple(warnings),
    )


def _all_events(library: ExportLibrary, run_id: str) -> list[DomainEvent]:
    events: list[DomainEvent] = []
    cursor = 0
    while True:
        page = library.list_events(run_id, cursor)
        events.extend(page.events)
        if not page.events or page.next_cursor <= cursor:
            return events
        cursor = page.next_cursor


def event_warnings(events: list[DomainEvent]) -> list[str]:
    """Classify warning-worthy events (step failures, errors, rate limits)."""
    warnings: list[str] = []
    for event in events:
        data = event.data
        if event.kind is EventKind.STEP_FAILED:
            step = data.get("step", "unknown")
            detail = data.get("error") or data.get("error_type") or ""
            warnings.append(f"步骤失败[{event.id}]: step={step} {detail}".rstrip())
            continue
        detail = data.get("error") or data.get("failure") or data.get("error_type")
        if detail:
            warnings.append(f"事件告警[{event.id}]: {detail}")
        if data.get("rate_limit") or data.get("rate_limited"):
            warnings.append(f"限流[{event.id}]: kind={event.kind}")
    return warnings


def run_warnings(
    library: ExportLibrary,
    content_store: ExportContentStore,
    run_id: str,
) -> list[str]:
    """Collect warnings shared by ``status`` and ``export``.

    Stale artifacts are intentionally excluded: they surface as a dedicated
    status field and as an export-specific note.
    """
    warnings: list[str] = []
    for artifact in library.list_artifacts(run_id):
        for note in artifact.submission.warnings:
            warnings.append(f"工件警告[{artifact.id}]: {note}")
    warnings.extend(event_warnings(_all_events(library, run_id)))
    _, evidence_warnings = _evidence_index(library, content_store, run_id)
    warnings.extend(evidence_warnings)
    return warnings


def _run_payload(run: ResearchRun, spec: RunSpec) -> dict[str, Any]:
    plan = run.plan
    return {
        "id": run.id,
        "project_id": run.project_id,
        "status": str(run.status),
        "checkpoint": run.checkpoint,
        "workflow_version": run.workflow_version,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "question": plan.question,
        "plan": {
            "question": plan.question,
            "include_terms": list(plan.include_terms),
            "exclude_terms": list(plan.exclude_terms),
            "languages": list(plan.languages),
            "source_kinds": [str(kind) for kind in plan.source_kinds],
            "start_date": plan.start_date,
            "end_date": plan.end_date,
            "seed_urls": list(plan.seed_urls),
        },
        "spec": {
            "skill_versions": dict(spec.skill_versions),
            "max_duration_seconds": spec.max_duration_seconds,
            "max_candidates": spec.max_candidates,
        },
    }


def _write_artifacts(
    library: ExportLibrary,
    destination: Path,
    artifacts: list[Artifact],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    used: set[str] = set()
    for artifact in artifacts:
        policy = _artifact_policy(library, artifact)
        relative = _artifact_path(library, artifact, used)
        written: str | None = None
        if policy is AccessPolicy.PERSIST:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(artifact.submission.markdown + "\n", encoding="utf-8")
            written = relative
        entries.append(
            {
                "id": artifact.id,
                "kind": str(artifact.submission.kind),
                "work_id": artifact.submission.work_id,
                "version": artifact.version,
                "skill_name": artifact.submission.skill_name,
                "skill_version": artifact.submission.skill_version,
                "evidence_ids": list(artifact.submission.evidence_ids),
                "validity": "valid",
                "policy": str(policy),
                "path": written,
                "warnings": list(artifact.submission.warnings),
            }
        )
    return entries


def _artifact_policy(library: ExportLibrary, artifact: Artifact) -> AccessPolicy:
    policies: list[AccessPolicy] = []
    for evidence_id in artifact.submission.evidence_ids:
        match = _EVIDENCE_ANCHOR.match(evidence_id)
        if match is None:
            continue
        try:
            source = library.get_source(match.group("source"))
        except KeyError:
            continue
        policies.append(source.access_policy)
    if AccessPolicy.METADATA_ONLY in policies:
        return AccessPolicy.METADATA_ONLY
    if AccessPolicy.CONTROLLED in policies:
        return AccessPolicy.CONTROLLED
    return AccessPolicy.PERSIST


def _artifact_path(library: ExportLibrary, artifact: Artifact, used: set[str]) -> str:
    kind = artifact.submission.kind
    if kind is ArtifactKind.SYNTHESIS:
        stem = "synthesis"
        relative = f"artifacts/{stem}.md"
    else:
        fallback = f"artifact-{artifact.id[:8]}"
        stem = _safe_filename(_work_title(library, artifact) or "", fallback)
        folder = "overviews" if kind is ArtifactKind.OVERVIEW else "analyses"
        relative = f"artifacts/{folder}/{stem}.md"
    if relative in used:
        base = relative[:-3]
        candidate = f"{base}-v{artifact.version}.md"
        relative = candidate if candidate not in used else f"{base}-{artifact.id[:8]}.md"
    used.add(relative)
    return relative


def _work_title(library: ExportLibrary, artifact: Artifact) -> str | None:
    work_id = artifact.submission.work_id
    if work_id is None:
        return None
    try:
        return library.get_work(work_id).title
    except KeyError:
        return None


def _safe_filename(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    cleaned = cleaned.strip(".-")[:_FILENAME_LIMIT].strip(".-")
    return cleaned or fallback


def _evidence_index(
    library: ExportLibrary,
    content_store: ExportContentStore,
    run_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    index: list[dict[str, Any]] = []
    warnings: list[str] = []
    for source_id in library.list_run_sources(run_id):
        try:
            source = library.get_source(source_id)
        except KeyError:
            warnings.append(f"来源 {source_id} 已删除或缺失, 仅记录标识")
            index.append(
                {
                    "id": source_id,
                    "work_id": None,
                    "kind": None,
                    "title": None,
                    "url": None,
                    "access_policy": None,
                    "content_available": False,
                }
            )
            continue
        try:
            title: str | None = library.get_work(source.work_id).title
        except KeyError:
            title = None
        content_available = False
        if source.access_policy is AccessPolicy.PERSIST:
            try:
                content_store.get(source.content_hash)
                content_available = True
            except (FileNotFoundError, ValueError):
                warnings.append(f"来源 {source_id} 的正文缺失 (digest {source.content_hash})")
        index.append(
            {
                "id": source.id,
                "work_id": source.work_id,
                "kind": str(source.source_ref.kind),
                "title": title,
                "url": source.canonical_url,
                "access_policy": str(source.access_policy),
                "content_available": content_available,
            }
        )
    return index, warnings


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_events(path: Path, events: list[DomainEvent]) -> None:
    lines = [
        json.dumps(
            {
                "id": event.id,
                "run_id": event.run_id,
                "sequence": event.sequence,
                "kind": str(event.kind),
                "occurred_at": event.occurred_at.isoformat(),
                "data": event.data,
            },
            ensure_ascii=False,
        )
        for event in events
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_warnings(path: Path, warnings: list[str]) -> None:
    lines = ["# 导出警告", ""]
    if warnings:
        lines.extend(f"- {note}" for note in warnings)
    else:
        lines.append("无警告。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
