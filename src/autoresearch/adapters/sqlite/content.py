"""Small content-addressed store with atomic writes and path confinement."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


class ContentStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("content digest must be a lowercase SHA-256 hex string")
        path = (self.objects / digest[:2] / f"{digest}.txt").resolve()
        if self.objects.resolve() not in path.parents:
            raise ValueError("content path escaped the store")
        return path

    def put(self, text: str) -> str:
        payload = text.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        target = self._path(digest)
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary_path = Path(temporary)
            if temporary_path.exists():
                temporary_path.unlink()
        return digest

    def get(self, digest: str) -> str:
        return self._path(digest).read_text(encoding="utf-8")

    def delete(self, digest: str) -> None:
        path = self._path(digest)
        if path.exists():
            path.unlink()
