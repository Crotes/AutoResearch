"""Transactional ResearchLibrary adapter backed by SQLite and local files.

# SQL statements are kept readable as adjacent literals; their line lengths do
# not affect generated SQL or the public adapter surface.
"""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from autoresearch.adapters.sqlite.connection import open_database
from autoresearch.adapters.sqlite.content import ContentStore
from autoresearch.application.artifacts import (
    ArtifactSubmissionValidator,
    JsonSchemaSkillOutputValidator,
)
from autoresearch.domain.library import (
    ArtifactValidity,
    ResearchProject,
    ReviewDecision,
    ReviewKind,
    ReviewOutcome,
    SkillVersion,
    Work,
)
from autoresearch.domain.models import (
    AccessPolicy,
    Artifact,
    ArtifactKind,
    ArtifactSubmission,
    ResearchPlan,
    ResearchRun,
    RunStatus,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
)
from autoresearch.ports.library import LibraryChunk, LibraryEntry

_ANCHOR = re.compile(r"^(?P<source>[^#]+)#chunk-(?P<index>[1-9]\d*)(?:@page-(?P<page>\d+))?$")


class IdempotencyConflict(ValueError):
    """The same idempotency key was reused for a different request."""


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value.isoformat()


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _plan_json(plan: ResearchPlan) -> str:
    return _json(
        {
            "question": plan.question,
            "include_terms": list(plan.include_terms),
            "exclude_terms": list(plan.exclude_terms),
            "languages": list(plan.languages),
            "source_kinds": [str(kind) for kind in plan.source_kinds],
            "start_date": plan.start_date,
            "end_date": plan.end_date,
            "seed_urls": list(plan.seed_urls),
        }
    )


def _plan_from_json(payload: str) -> ResearchPlan:
    data = json.loads(payload)
    return ResearchPlan(
        question=data["question"],
        include_terms=tuple(data["include_terms"]),
        exclude_terms=tuple(data["exclude_terms"]),
        languages=tuple(data["languages"]),
        source_kinds=tuple(SourceKind(value) for value in data["source_kinds"]),
        start_date=data["start_date"],
        end_date=data["end_date"],
        seed_urls=tuple(data["seed_urls"]),
    )


def _artifact_request_hash(run_id: str, submission: ArtifactSubmission) -> str:
    payload = {"run_id": run_id, **asdict(submission), "kind": str(submission.kind)}
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


class SqliteResearchLibrary:
    """The write boundary for persistent facts and derived search indexes.

    Every public write opens a short ``BEGIN IMMEDIATE`` transaction.  The
    adapter intentionally exposes domain records rather than SQLite rows so a
    later PostgreSQL adapter can implement the same seam.
    """

    def __init__(
        self,
        database: str | Path,
        content_root: str | Path | None = None,
        artifact_validator: ArtifactSubmissionValidator | None = None,
    ) -> None:
        self.database_path = str(database)
        root = Path(content_root) if content_root is not None else Path(str(database) + ".content")
        self.content = ContentStore(root)
        self.connection = open_database(database)
        self._lock = threading.RLock()
        self._artifact_validator = artifact_validator or JsonSchemaSkillOutputValidator()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> SqliteResearchLibrary:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
            except BaseException:
                self.connection.rollback()
                raise
            else:
                self.connection.commit()

    # -- project/run/skill/work/source -------------------------------------

    def save_project(self, project: ResearchProject) -> ResearchProject:
        with self._transaction() as db:
            db.execute(
                "INSERT INTO projects(id,name,description) VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, description=excluded.description",
                (project.id, project.name, project.description),
            )
        return project

    def get_project(self, project_id: str) -> ResearchProject:
        with self._lock:
            row = self.connection.execute(
                "SELECT id,name,description FROM projects WHERE id=?", (project_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown project: {project_id}")
        return ResearchProject(id=row["id"], name=row["name"], description=row["description"])

    def save_skill_version(self, skill: SkillVersion) -> SkillVersion:
        with self._transaction() as db:
            db.execute(
                "INSERT INTO skill_versions(name,version,manifest_hash,source_ref) VALUES (?,?,?,?) "
                "ON CONFLICT(name,version) DO UPDATE SET manifest_hash=excluded.manifest_hash, source_ref=excluded.source_ref",
                (skill.name, skill.version, skill.manifest_hash, skill.source_ref),
            )
        return skill

    def save_run(
        self, run: ResearchRun, skill_versions: Sequence[SkillVersion] = ()
    ) -> ResearchRun:
        with self._transaction() as db:
            db.execute(
                "INSERT INTO projects(id,name) VALUES (?,?) ON CONFLICT(id) DO NOTHING",
                (run.project_id, run.project_id),
            )
            db.execute(
                "INSERT INTO runs(id,project_id,status,plan_json,workflow_version,created_at,updated_at,checkpoint) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
                "plan_json=excluded.plan_json, workflow_version=excluded.workflow_version, "
                "updated_at=excluded.updated_at, checkpoint=excluded.checkpoint",
                (
                    run.id,
                    run.project_id,
                    str(run.status),
                    _plan_json(run.plan),
                    run.workflow_version,
                    _stamp(run.created_at),
                    _stamp(run.updated_at),
                    run.checkpoint,
                ),
            )
            for skill in skill_versions:
                db.execute(
                    "INSERT INTO skill_versions(name,version,manifest_hash,source_ref) VALUES (?,?,?,?) "
                    "ON CONFLICT(name,version) DO NOTHING",
                    (skill.name, skill.version, skill.manifest_hash, skill.source_ref),
                )
                db.execute(
                    "INSERT INTO run_skill_versions(run_id,name,version) VALUES (?,?,?) "
                    "ON CONFLICT(run_id,name) DO UPDATE SET version=excluded.version",
                    (run.id, skill.name, skill.version),
                )
        return run

    def get_run(self, run_id: str) -> ResearchRun:
        with self._lock:
            row = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown run: {run_id}")
        return ResearchRun(
            id=row["id"],
            project_id=row["project_id"],
            status=RunStatus(row["status"]),
            plan=_plan_from_json(row["plan_json"]),
            workflow_version=row["workflow_version"],
            created_at=_time(row["created_at"]),
            updated_at=_time(row["updated_at"]),
            checkpoint=row["checkpoint"],
        )

    def save_work(self, work: Work) -> Work:
        metadata = work.metadata or {}
        with self._transaction() as db:
            existing_work_ids: set[str] = set()
            for identity_key in work.identity_keys:
                existing = db.execute(
                    "SELECT work_id FROM work_identity_keys WHERE identity_key=?", (identity_key,)
                ).fetchone()
                if existing is not None:
                    existing_work_ids.add(str(existing[0]))
            if len(existing_work_ids) > 1:
                raise ValueError("identity keys resolve to different works; merge them explicitly")
            canonical_id = next(iter(existing_work_ids), work.id)
            if canonical_id == work.id:
                db.execute(
                    "INSERT INTO works(id,title,metadata_json) VALUES (?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
                    "metadata_json=excluded.metadata_json",
                    (canonical_id, work.title, _json(metadata)),
                )
            for identity_key in work.identity_keys:
                db.execute(
                    "INSERT INTO work_identity_keys(identity_key,work_id) VALUES (?,?) "
                    "ON CONFLICT(identity_key) DO NOTHING",
                    (identity_key, canonical_id),
                )
        return self.get_work(canonical_id)

    def get_work(self, work_id: str) -> Work:
        with self._lock:
            row = self.connection.execute(
                "SELECT id,title,metadata_json FROM works WHERE id=?", (work_id,)
            ).fetchone()
            keys = self.connection.execute(
                "SELECT identity_key FROM work_identity_keys WHERE work_id=? ORDER BY identity_key",
                (work_id,),
            ).fetchall()
        if row is None:
            raise KeyError(f"unknown work: {work_id}")
        metadata = json.loads(row["metadata_json"])
        return Work(
            id=row["id"],
            title=row["title"],
            identity_keys=tuple(str(item[0]) for item in keys),
            metadata=metadata or None,
        )

    def resolve_work(self, identity_key: str) -> str | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT work_id FROM work_identity_keys WHERE identity_key=?", (identity_key,)
            ).fetchone()
        return None if row is None else str(row[0])

    def save_source(self, document: SourceDocument) -> str:
        source = document.source_version
        with self._transaction() as db:
            existing = db.execute(
                "SELECT id,access_policy,deleted_at FROM source_versions "
                "WHERE source_kind=? AND canonical_url=? AND content_hash=?",
                (str(source.source_ref.kind), source.canonical_url, source.content_hash),
            ).fetchone()
            source_id = str(existing[0]) if existing is not None else source.id
            existing_policy = AccessPolicy(existing[1]) if existing is not None else None
            if (
                existing_policy is AccessPolicy.PERSIST
                and source.access_policy is not AccessPolicy.PERSIST
                and existing[2] is None
            ):
                return source_id
            persist_body = (
                source.access_policy is AccessPolicy.PERSIST
                or existing_policy is AccessPolicy.PERSIST
            )
            effective_policy = AccessPolicy.PERSIST if persist_body else source.access_policy
            blob_hash = self.content.put(document.text) if persist_body else None
            db.execute(
                "INSERT INTO works(id,title) VALUES (?,?) ON CONFLICT(id) DO NOTHING",
                (source.work_id, source.canonical_url),
            )
            db.execute(
                "INSERT INTO source_versions(id,work_id,source_kind,locator,canonical_url,retrieved_at,content_hash,access_policy,license,media_type,blob_hash,deleted_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL) ON CONFLICT(id) DO UPDATE SET "
                "retrieved_at=excluded.retrieved_at, access_policy=excluded.access_policy, "
                "license=excluded.license, media_type=excluded.media_type, "
                "deleted_at=NULL, blob_hash=excluded.blob_hash",
                (
                    source_id,
                    source.work_id,
                    str(source.source_ref.kind),
                    source.source_ref.locator,
                    source.canonical_url,
                    _stamp(source.retrieved_at),
                    source.content_hash,
                    str(effective_policy),
                    source.license,
                    document.media_type,
                    blob_hash,
                ),
            )
            db.execute("DELETE FROM source_chunks WHERE source_version_id=?", (source_id,))
            db.execute("DELETE FROM source_chunks_fts WHERE source_version_id=?", (source_id,))
            if persist_body:
                for index, text in enumerate(document.chunks, start=1):
                    db.execute(
                        "INSERT INTO source_chunks(source_version_id,chunk_index,text) VALUES (?,?,?)",
                        (source_id, index, text),
                    )
                    db.execute(
                        "INSERT INTO source_chunks_fts(source_version_id,chunk_index,text) VALUES (?,?,?)",
                        (source_id, index, text),
                    )
        return source_id

    def get_source(self, source_version_id: str) -> SourceVersion:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM source_versions WHERE id=? AND deleted_at IS NULL",
                (source_version_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown or deleted source version: {source_version_id}")
        return SourceVersion(
            id=row["id"],
            work_id=row["work_id"],
            source_ref=SourceRef(kind=SourceKind(row["source_kind"]), locator=row["locator"]),
            canonical_url=row["canonical_url"],
            retrieved_at=_time(row["retrieved_at"]),
            content_hash=row["content_hash"],
            access_policy=AccessPolicy(row["access_policy"]),
            license=row["license"],
        )

    # -- artifacts and evidence -------------------------------------------

    def _validate_submission(self, submission: ArtifactSubmission) -> None:
        if not isinstance(submission.kind, ArtifactKind):
            raise ValueError("artifact kind is invalid")
        if not isinstance(submission.markdown, str) or not submission.markdown.strip():
            raise ValueError("artifact markdown must not be empty")
        if not isinstance(submission.structured, dict):
            raise ValueError("artifact structured payload must be an object")
        if not submission.evidence_ids:
            raise ValueError("artifact requires evidence")
        if len(set(submission.evidence_ids)) != len(submission.evidence_ids):
            raise ValueError("artifact evidence ids must be unique")
        if any(not isinstance(item, str) or not item.strip() for item in submission.evidence_ids):
            raise ValueError("artifact evidence ids must be non-empty strings")
        if any(not isinstance(item, str) for item in submission.warnings):
            raise ValueError("artifact warnings must be strings")
        if len(set(submission.dependency_artifact_ids)) != len(submission.dependency_artifact_ids):
            raise ValueError("artifact dependency ids must be unique")
        if not submission.skill_name.strip() or not submission.skill_version.strip():
            raise ValueError("artifact skill identity is required")

    def submit(self, run_id: str, submission: ArtifactSubmission) -> Artifact:
        artifact, _ = self._submit(run_id, submission, None, None)
        return artifact

    def submit_idempotent(
        self, run_id: str, idempotency_key: str, submission: ArtifactSubmission
    ) -> tuple[Artifact, bool]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key must not be empty")
        return self._submit(
            run_id, submission, idempotency_key, _artifact_request_hash(run_id, submission)
        )

    def _submit(
        self,
        run_id: str,
        submission: ArtifactSubmission,
        idempotency_key: str | None,
        request_hash: str | None,
    ) -> tuple[Artifact, bool]:
        self._validate_submission(submission)
        self._artifact_validator.validate(submission)
        now = _now()
        with self._transaction() as db:
            if idempotency_key is not None and request_hash is not None:
                old = db.execute(
                    "SELECT request_hash,artifact_id FROM idempotency_keys WHERE run_id=? AND idempotency_key=?",
                    (run_id, idempotency_key),
                ).fetchone()
                if old is not None:
                    if old[0] != request_hash:
                        raise IdempotencyConflict(
                            "idempotency key was reused for a different submission"
                        )
                    return self._artifact_by_id(db, str(old[1])), True
            for evidence_id in submission.evidence_ids:
                match = _ANCHOR.fullmatch(evidence_id)
                if match is None:
                    raise ValueError(f"invalid evidence anchor: {evidence_id!r}")
                source_id = match.group("source")
                chunk_index = int(match.group("index"))
                source = db.execute(
                    "SELECT deleted_at FROM source_versions WHERE id=?", (source_id,)
                ).fetchone()
                if source is None or source[0] is not None:
                    raise ValueError(f"evidence source is unavailable: {source_id}")
                chunk = db.execute(
                    "SELECT 1 FROM source_chunks WHERE source_version_id=? AND chunk_index=?",
                    (source_id, chunk_index),
                ).fetchone()
                if chunk is None:
                    raise ValueError(f"evidence chunk does not exist: {evidence_id}")
            version_row = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM artifacts WHERE run_id=? AND kind=? AND work_id IS ?",
                (run_id, str(submission.kind), submission.work_id),
            ).fetchone()
            version = int(version_row[0])
            artifact_id = f"artifact-{uuid4().hex}"
            db.execute(
                "INSERT INTO artifacts(id,run_id,version,kind,work_id,created_at,markdown,structured_json,warnings_json,skill_name,skill_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    artifact_id,
                    run_id,
                    version,
                    str(submission.kind),
                    submission.work_id,
                    _stamp(now),
                    submission.markdown,
                    _json(submission.structured),
                    _json(list(submission.warnings)),
                    submission.skill_name,
                    submission.skill_version,
                ),
            )
            for evidence_id in submission.evidence_ids:
                match = _ANCHOR.fullmatch(evidence_id)
                assert match is not None
                db.execute(
                    "INSERT OR IGNORE INTO evidence(id,source_version_id,chunk_index) VALUES (?,?,?)",
                    (evidence_id, match.group("source"), int(match.group("index"))),
                )
                db.execute(
                    "INSERT INTO artifact_evidence(artifact_id,evidence_id) VALUES (?,?)",
                    (artifact_id, evidence_id),
                )
            for dependency in submission.dependency_artifact_ids:
                dependency_row = db.execute(
                    "SELECT validity FROM artifacts WHERE id=?", (dependency,)
                ).fetchone()
                if dependency_row is None:
                    raise ValueError(f"dependency artifact does not exist: {dependency}")
                if ArtifactValidity(dependency_row[0]) is not ArtifactValidity.VALID:
                    raise ValueError(f"dependency artifact is stale: {dependency}")
                db.execute(
                    "INSERT INTO artifact_dependencies(artifact_id,depends_on_artifact_id) VALUES (?,?)",
                    (artifact_id, dependency),
                )
            title = str(submission.structured.get("title", submission.kind.value))
            summary = str(submission.structured.get("summary", submission.markdown[:280]))
            db.execute(
                "INSERT INTO artifacts_fts(artifact_id,title,summary,body) VALUES (?,?,?,?)",
                (artifact_id, title, summary, submission.markdown),
            )
            if idempotency_key is not None and request_hash is not None:
                db.execute(
                    "INSERT INTO idempotency_keys(run_id,idempotency_key,request_hash,artifact_id) VALUES (?,?,?,?)",
                    (run_id, idempotency_key, request_hash, artifact_id),
                )
            return self._artifact_by_id(db, artifact_id), False

    def _artifact_by_id(self, db: sqlite3.Connection, artifact_id: str) -> Artifact:
        row = db.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown artifact: {artifact_id}")
        evidence_rows = db.execute(
            "SELECT evidence_id FROM artifact_evidence WHERE artifact_id=? ORDER BY evidence_id",
            (artifact_id,),
        ).fetchall()
        dependency_rows = db.execute(
            "SELECT depends_on_artifact_id FROM artifact_dependencies WHERE artifact_id=? ORDER BY depends_on_artifact_id",
            (artifact_id,),
        ).fetchall()
        submission = ArtifactSubmission(
            kind=ArtifactKind(row["kind"]),
            work_id=row["work_id"],
            markdown=row["markdown"],
            structured=json.loads(row["structured_json"]),
            evidence_ids=tuple(str(item[0]) for item in evidence_rows),
            warnings=tuple(json.loads(row["warnings_json"])),
            skill_name=row["skill_name"],
            skill_version=row["skill_version"],
            dependency_artifact_ids=tuple(str(item[0]) for item in dependency_rows),
        )
        return Artifact(
            id=row["id"],
            run_id=row["run_id"],
            version=int(row["version"]),
            created_at=_time(row["created_at"]),
            submission=submission,
        )

    def get_artifact(self, artifact_id: str) -> Artifact:
        with self._lock:
            return self._artifact_by_id(self.connection, artifact_id)

    def artifact_validity(self, artifact_id: str) -> ArtifactValidity:
        with self._lock:
            row = self.connection.execute(
                "SELECT validity FROM artifacts WHERE id=?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown artifact: {artifact_id}")
        return ArtifactValidity(row[0])

    # -- search and source reads -------------------------------------------

    def search(self, query: str, *, limit: int = 10) -> tuple[LibraryEntry, ...]:
        if limit <= 0:
            return ()
        terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
        if not terms:
            return ()
        match_query = " AND ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        with self._lock:
            rows = self.connection.execute(
                "SELECT a.id,a.run_id,a.kind,a.work_id,f.title,f.summary,a.validity FROM artifacts_fts f "
                "JOIN artifacts a ON a.id=f.artifact_id WHERE a.validity='valid' AND artifacts_fts MATCH ? "
                "ORDER BY a.created_at DESC LIMIT ?",
                (match_query, limit),
            ).fetchall()
        return tuple(
            LibraryEntry(
                artifact_id=row["id"],
                run_id=row["run_id"],
                kind=ArtifactKind(row["kind"]),
                title=row["title"],
                summary=row["summary"],
                work_id=row["work_id"],
                validity=ArtifactValidity(row["validity"]),
            )
            for row in rows
        )

    def read_chunks(
        self, source_version_id: str, *, start: int = 0, limit: int = 5
    ) -> tuple[LibraryChunk, ...]:
        if limit <= 0:
            return ()
        first = max(start, 1)
        with self._lock:
            rows = self.connection.execute(
                "SELECT chunk_index,text FROM source_chunks WHERE source_version_id=? AND chunk_index>=? "
                "AND EXISTS (SELECT 1 FROM source_versions WHERE id=? AND deleted_at IS NULL) "
                "ORDER BY chunk_index LIMIT ?",
                (source_version_id, first, source_version_id, limit),
            ).fetchall()
            if not rows:
                exists = self.connection.execute(
                    "SELECT 1 FROM source_versions WHERE id=? AND deleted_at IS NULL",
                    (source_version_id,),
                ).fetchone()
            else:
                exists = True
            if exists is None:
                raise KeyError(f"unknown or deleted source version: {source_version_id}")
        return tuple(
            LibraryChunk(source_version_id=source_version_id, index=int(row[0]), text=row[1])
            for row in rows
        )

    # -- append-only reviews and invalidation ------------------------------

    def add_review(self, decision: ReviewDecision) -> ReviewDecision:
        with self._transaction() as db:
            row = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM review_decisions WHERE run_id=?",
                (decision.run_id,),
            ).fetchone()
            db.execute(
                "INSERT INTO review_decisions(id,run_id,kind,outcome,reviewer,comment,created_at,artifact_id,supersedes_id,sequence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    decision.id,
                    decision.run_id,
                    str(decision.kind),
                    str(decision.outcome),
                    decision.reviewer,
                    decision.comment,
                    _stamp(decision.created_at),
                    decision.artifact_id,
                    decision.supersedes_id,
                    int(row[0]),
                ),
            )
            for work_id in decision.work_ids:
                db.execute(
                    "INSERT INTO review_decision_works(review_id,work_id) VALUES (?,?)",
                    (decision.id, work_id),
                )
        return decision

    def list_reviews(self, run_id: str) -> tuple[ReviewDecision, ...]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM review_decisions WHERE run_id=? ORDER BY sequence", (run_id,)
            ).fetchall()
            work_rows = self.connection.execute(
                "SELECT rw.review_id,rw.work_id FROM review_decision_works rw "
                "JOIN review_decisions r ON r.id=rw.review_id WHERE r.run_id=? "
                "ORDER BY rw.review_id,rw.work_id",
                (run_id,),
            ).fetchall()
        work_ids: dict[str, list[str]] = {}
        for item in work_rows:
            work_ids.setdefault(str(item[0]), []).append(str(item[1]))
        return tuple(
            ReviewDecision(
                id=row["id"],
                run_id=row["run_id"],
                kind=ReviewKind(row["kind"]),
                outcome=ReviewOutcome(row["outcome"]),
                reviewer=row["reviewer"],
                comment=row["comment"],
                created_at=_time(row["created_at"]),
                artifact_id=row["artifact_id"],
                supersedes_id=row["supersedes_id"],
                work_ids=tuple(work_ids.get(str(row["id"]), ())),
            )
            for row in rows
        )

    def delete_source(self, source_version_id: str) -> tuple[str, ...]:
        deleted_blob: str | None = None
        invalidated: set[str] = set()
        with self._transaction() as db:
            row = db.execute(
                "SELECT blob_hash,deleted_at FROM source_versions WHERE id=?", (source_version_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown source version: {source_version_id}")
            if row[1] is not None:
                return ()
            deleted_blob = row[0]
            direct = db.execute(
                "SELECT DISTINCT ae.artifact_id FROM artifact_evidence ae "
                "JOIN evidence e ON e.id=ae.evidence_id WHERE e.source_version_id=?",
                (source_version_id,),
            ).fetchall()
            pending = [str(item[0]) for item in direct]
            invalidated.update(pending)
            while pending:
                parents = db.execute(
                    f"SELECT artifact_id FROM artifact_dependencies WHERE depends_on_artifact_id IN "
                    f"({','.join('?' for _ in pending)})",
                    pending,
                ).fetchall()
                pending = [str(item[0]) for item in parents if str(item[0]) not in invalidated]
                invalidated.update(pending)
            now = _stamp(_now())
            for artifact_id in invalidated:
                db.execute(
                    "UPDATE artifacts SET validity='stale', invalidated_at=? WHERE id=?",
                    (now, artifact_id),
                )
                db.execute(
                    "INSERT OR IGNORE INTO artifact_invalidations(artifact_id,source_version_id,reason,created_at) VALUES (?,?,?,?)",
                    (artifact_id, source_version_id, "source_deleted", now),
                )
            db.execute(
                "DELETE FROM source_chunks_fts WHERE source_version_id=?", (source_version_id,)
            )
            db.execute("DELETE FROM source_chunks WHERE source_version_id=?", (source_version_id,))
            db.execute(
                "UPDATE source_versions SET deleted_at=?, blob_hash=NULL WHERE id=?",
                (now, source_version_id),
            )
            if deleted_blob is not None:
                db.execute(
                    "INSERT OR IGNORE INTO blob_gc_queue(blob_hash,queued_at) VALUES (?,?)",
                    (deleted_blob, now),
                )
        if deleted_blob is not None:
            with self._lock:
                still_used = self.connection.execute(
                    "SELECT 1 FROM source_versions WHERE blob_hash=? AND deleted_at IS NULL LIMIT 1",
                    (deleted_blob,),
                ).fetchone()
            if still_used is None:
                self.content.delete(deleted_blob)
                with self._transaction() as db:
                    db.execute("DELETE FROM blob_gc_queue WHERE blob_hash=?", (deleted_blob,))
        return tuple(sorted(invalidated))
