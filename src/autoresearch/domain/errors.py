"""Stable error categories used by workflow policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CONTENT = "content"
    MODEL = "model"
    POLICY = "policy"
    INTERNAL = "internal"


_DEFAULT_RETRYABILITY: dict[ErrorCategory, bool] = {
    ErrorCategory.TRANSIENT: True,
    ErrorCategory.PERMANENT: False,
    ErrorCategory.CONTENT: False,
    ErrorCategory.MODEL: True,
    ErrorCategory.POLICY: False,
    ErrorCategory.INTERNAL: False,
}


@dataclass(frozen=True, slots=True)
class Failure:
    category: ErrorCategory
    code: str
    message: str
    retryable: bool | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def should_retry(self) -> bool:
        if self.retryable is not None:
            return self.retryable
        return _DEFAULT_RETRYABILITY[self.category]


class AutoResearchError(Exception):
    """Exception wrapper that preserves workflow-visible failure details."""

    def __init__(self, failure: Failure) -> None:
        super().__init__(failure.message)
        self.failure = failure
