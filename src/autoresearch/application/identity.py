"""Work identity resolution: four signal levels plus human corrections.

Signal priority: DOI > arXiv id > normalized GitHub repo URL > normalized
title + first author. ``resolve_work_id`` is deterministic; operators may
append merge/split corrections (JSONL) that override the heuristic outcome.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from autoresearch.adapters.sources.normalize import normalize_github_url

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class IdentitySignals:
    doi: str | None = None
    arxiv_id: str | None = None
    repo_url: str | None = None
    title: str | None = None
    first_author: str | None = None


def identity_key(signals: IdentitySignals) -> str:
    """The deterministic identity key for a set of signals."""
    if signals.doi:
        return f"doi:{signals.doi.strip().lower()}"
    if signals.arxiv_id:
        arxiv_id = signals.arxiv_id.strip().split("v")[0].lower()
        return f"arxiv:{arxiv_id}"
    if signals.repo_url:
        return f"repo:{normalize_github_url(signals.repo_url)}"
    if signals.title:
        title = _normalize_phrase(signals.title)
        author = _normalize_phrase(signals.first_author or "")
        return f"title:{title}|{author}"
    raise ValueError("insufficient identity signals")


def resolve_work_id(
    signals: IdentitySignals, corrections: IdentityCorrections | None = None
) -> str:
    key = identity_key(signals)
    work_id = "work-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    if corrections is not None:
        return corrections.apply(work_id, key)
    return work_id


def _normalize_phrase(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = _PUNCTUATION.sub(" ", normalized)
    return _WHITESPACE.sub(" ", normalized).strip()


class IdentityCorrections:
    """Append-only merge/split records overriding heuristic work ids."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._merges: dict[str, str] = {}
        self._splits: dict[str, str] = {}
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                self._apply_record(record)

    def record_merge(self, source_work_id: str, target_work_id: str) -> None:
        """Fold ``source_work_id`` into ``target_work_id`` from now on."""
        record = {"action": "merge", "source": source_work_id, "target": target_work_id}
        self._apply_record(record)
        self._append(record)

    def record_split(self, work_id: str, member_key: str) -> None:
        """Give one member of a wrongly-merged work its own work id."""
        record = {"action": "split", "work_id": work_id, "member_key": member_key}
        self._apply_record(record)
        self._append(record)

    def apply(self, work_id: str, key: str) -> str:
        split_key = f"{work_id}|{key}"
        if split_key in self._splits:
            return self._splits[split_key]
        seen = set()
        current = work_id
        while current in self._merges and current not in seen:
            seen.add(current)
            current = self._merges[current]
        return current

    def _apply_record(self, record: dict[str, str]) -> None:
        if record.get("action") == "merge":
            self._merges[record["source"]] = record["target"]
        elif record.get("action") == "split":
            member = f"{record['work_id']}|{record['member_key']}"
            digest = hashlib.sha256(f"split:{member}".encode()).hexdigest()[:12]
            self._splits[member] = f"work-{digest}"

    def _append(self, record: dict[str, str]) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
