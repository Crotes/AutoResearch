"""Concrete adapters for external and in-memory boundaries."""

from autoresearch.adapters.fake import FakeRuntimeAdapter, InMemorySourceAdapter
from autoresearch.adapters.library import InMemoryLibrarySearch

__all__ = ["FakeRuntimeAdapter", "InMemoryLibrarySearch", "InMemorySourceAdapter"]
