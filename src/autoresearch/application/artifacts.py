"""Runtime validation of Skill-produced artifact submissions."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Protocol

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from referencing import Registry, Resource

from autoresearch.domain.models import ArtifactSubmission

_SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ArtifactSubmissionValidator(Protocol):
    def validate(self, submission: ArtifactSubmission) -> None: ...


class SkillSchemaValidationError(ValueError):
    """A Skill output did not satisfy its versioned output Schema."""


class JsonSchemaSkillOutputValidator:
    """Validate artifact-producing Skill payloads against their output Schema.

    Triage and synthesis Skills persist one artifact at a time, while their
    final output Schema also contains the review envelope.  The adapter builds
    that deterministic envelope for validation without changing stored data.
    """

    def __init__(self, skills_root: str | Path | None = None) -> None:
        self.skills_root = (
            Path(skills_root)
            if skills_root is not None
            else Path(__file__).resolve().parents[3] / "skills"
        )
        shared_path = self.skills_root / "_shared" / "output-envelope.schema.json"
        shared = json.loads(shared_path.read_text(encoding="utf-8"))
        self._registry = Registry().with_resource(
            str(shared["$id"]), Resource.from_contents(shared)
        )
        self._validators: dict[str, Draft202012Validator] = {}

    def validate(self, submission: ArtifactSubmission) -> None:
        validator = self._validator(submission.skill_name)
        envelope = self._envelope(submission)
        errors = sorted(validator.iter_errors(envelope), key=lambda error: list(error.path))
        if not errors:
            return
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "output"
        raise SkillSchemaValidationError(
            f"skill output schema rejected {submission.skill_name}@{submission.skill_version} "
            f"at {location}: {first.message}"
        )

    def _validator(self, skill_name: str) -> Draft202012Validator:
        if _SKILL_NAME.fullmatch(skill_name) is None:
            raise SkillSchemaValidationError(
                f"invalid skill name for schema lookup: {skill_name!r}"
            )
        cached = self._validators.get(skill_name)
        if cached is not None:
            return cached
        path = self.skills_root / skill_name / "output.schema.json"
        if not path.is_file():
            raise SkillSchemaValidationError(f"skill output schema does not exist: {skill_name!r}")
        schema = json.loads(path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(
            schema,
            registry=self._registry,
            format_checker=FormatChecker(),
        )
        self._validators[skill_name] = validator
        return validator

    @staticmethod
    def _envelope(submission: ArtifactSubmission) -> dict[str, object]:
        structured = deepcopy(submission.structured)
        if submission.skill_name == "triage-sources":
            structured = {
                "overviews": [structured],
                "review": {"gate": "source_selection", "status": "pending"},
            }
        elif submission.skill_name == "synthesize-topic" and "review" not in structured:
            structured["review"] = {"gate": "final_approval", "status": "pending"}
        return {
            "schema_version": "1.0",
            "skill": {"name": submission.skill_name, "version": submission.skill_version},
            "markdown": submission.markdown,
            "structured": structured,
            "evidence": [],
            "evidence_ids": list(submission.evidence_ids),
            "warnings": list(submission.warnings),
        }
