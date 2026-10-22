"""Concrete adapters for external and in-memory boundaries."""

from autoresearch.adapters.fake import FakeRuntimeAdapter, InMemorySourceAdapter

__all__ = ["FakeRuntimeAdapter", "InMemorySourceAdapter"]
