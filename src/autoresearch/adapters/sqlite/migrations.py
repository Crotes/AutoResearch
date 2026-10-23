"""Versioned SQLite schema for the PoC library."""
# ruff: noqa: E501

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    current = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()[0]
    if current >= SCHEMA_VERSION:
        return
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          status TEXT NOT NULL, plan_json TEXT NOT NULL, workflow_version TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS skill_versions (
          name TEXT NOT NULL, version TEXT NOT NULL, manifest_hash TEXT NOT NULL DEFAULT '',
          source_ref TEXT NOT NULL DEFAULT '', PRIMARY KEY(name, version)
        );
        CREATE TABLE IF NOT EXISTS run_skill_versions (
          run_id TEXT NOT NULL REFERENCES runs(id), name TEXT NOT NULL, version TEXT NOT NULL,
          PRIMARY KEY(run_id, name), FOREIGN KEY(name, version) REFERENCES skill_versions(name, version)
        );
        CREATE TABLE IF NOT EXISTS works (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS work_identity_keys (
          identity_key TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id)
        );
        CREATE TABLE IF NOT EXISTS source_versions (
          id TEXT PRIMARY KEY, work_id TEXT NOT NULL REFERENCES works(id), source_kind TEXT NOT NULL,
          locator TEXT NOT NULL, canonical_url TEXT NOT NULL, retrieved_at TEXT NOT NULL,
          content_hash TEXT NOT NULL, access_policy TEXT NOT NULL, license TEXT, media_type TEXT NOT NULL,
          blob_hash TEXT, deleted_at TEXT,
          UNIQUE(source_kind, canonical_url, content_hash)
        );
        CREATE TABLE IF NOT EXISTS source_chunks (
          source_version_id TEXT NOT NULL REFERENCES source_versions(id) ON DELETE CASCADE,
          chunk_index INTEGER NOT NULL CHECK(chunk_index > 0), text TEXT NOT NULL,
          PRIMARY KEY(source_version_id, chunk_index)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS source_chunks_fts USING fts5(
          source_version_id UNINDEXED, chunk_index UNINDEXED, text
        );
        CREATE TABLE IF NOT EXISTS artifacts (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), version INTEGER NOT NULL,
          kind TEXT NOT NULL, work_id TEXT, created_at TEXT NOT NULL, markdown TEXT NOT NULL,
          structured_json TEXT NOT NULL, warnings_json TEXT NOT NULL, skill_name TEXT NOT NULL,
          skill_version TEXT NOT NULL, validity TEXT NOT NULL DEFAULT 'valid', invalidated_at TEXT,
          UNIQUE(run_id, kind, work_id, version)
        );
        CREATE TABLE IF NOT EXISTS evidence (
          id TEXT PRIMARY KEY, source_version_id TEXT NOT NULL REFERENCES source_versions(id),
          chunk_index INTEGER NOT NULL CHECK(chunk_index > 0), quote TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS artifact_evidence (
          artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
          evidence_id TEXT NOT NULL REFERENCES evidence(id), PRIMARY KEY(artifact_id, evidence_id)
        );
        CREATE TABLE IF NOT EXISTS artifact_dependencies (
          artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
          depends_on_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
          PRIMARY KEY(artifact_id, depends_on_artifact_id)
        );
        CREATE TABLE IF NOT EXISTS artifact_invalidations (
          artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
          source_version_id TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(artifact_id, source_version_id)
        );
        CREATE TABLE IF NOT EXISTS review_decisions (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), kind TEXT NOT NULL,
          outcome TEXT NOT NULL, reviewer TEXT NOT NULL, comment TEXT NOT NULL, created_at TEXT NOT NULL,
          artifact_id TEXT, supersedes_id TEXT, sequence INTEGER NOT NULL,
          UNIQUE(run_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS idempotency_keys (
          run_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
          artifact_id TEXT NOT NULL REFERENCES artifacts(id), PRIMARY KEY(run_id, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS blob_gc_queue (
          blob_hash TEXT PRIMARY KEY, queued_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts USING fts5(
          artifact_id UNINDEXED, title, summary, body
        );
        CREATE INDEX IF NOT EXISTS idx_source_versions_work ON source_versions(work_id);
        CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
        CREATE INDEX IF NOT EXISTS idx_invalidations_artifact ON artifact_invalidations(artifact_id);
        """
    )
    from datetime import UTC, datetime

    applied_at = datetime.now(UTC).isoformat()
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (1, applied_at),
    )
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
    if "checkpoint" not in columns:
        connection.execute("ALTER TABLE runs ADD COLUMN checkpoint TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS review_decision_works (
          review_id TEXT NOT NULL REFERENCES review_decisions(id) ON DELETE CASCADE,
          work_id TEXT NOT NULL REFERENCES works(id),
          PRIMARY KEY(review_id, work_id)
        )
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (2, applied_at),
    )
