from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "name", ["run", "source", "artifact", "event", "review-decision", "skill-version"]
)
def test_example_satisfies_contract(name: str) -> None:
    schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "contracts" / f"{name}.json").read_text(encoding="utf-8")
    )

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(fixture)


def test_event_contract_rejects_runtime_specific_event() -> None:
    schema = json.loads((ROOT / "schemas" / "event.schema.json").read_text(encoding="utf-8"))
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "contracts" / "event.json").read_text(encoding="utf-8")
    )
    fixture["kind"] = "pi.agent_end"

    errors = list(Draft202012Validator(schema).iter_errors(fixture))

    assert errors
