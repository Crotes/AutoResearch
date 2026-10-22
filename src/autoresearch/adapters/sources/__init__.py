"""Networked source connectors (arXiv, GitHub, RSS, manual URL)."""

from autoresearch.adapters.sources.arxiv import ArxivSource
from autoresearch.adapters.sources.composite import CompositeSourceAdapter
from autoresearch.adapters.sources.github import GitHubSource
from autoresearch.adapters.sources.http import (
    FileCache,
    HttpClient,
    HttpRequest,
    HttpResponse,
)
from autoresearch.adapters.sources.manual import ManualUrlSource
from autoresearch.adapters.sources.rss import RssSource

__all__ = [
    "ArxivSource",
    "CompositeSourceAdapter",
    "FileCache",
    "GitHubSource",
    "HttpClient",
    "HttpRequest",
    "HttpResponse",
    "ManualUrlSource",
    "RssSource",
]
