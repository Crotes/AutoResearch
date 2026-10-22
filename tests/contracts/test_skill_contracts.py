from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).parents[2]
SKILLS_ROOT = ROOT / "skills"
REQUIRED_FILES = {
    "SKILL.md",
    "input.schema.json",
    "output.schema.json",
    "examples/case.json",
    "EXPECTED.md",
    "CHANGELOG.md",
    "UPSTREAM.md",
}
KNOWN_TOOLS = {
    "discover_sources",
    "materialize_source",
    "search_library",
    "read_source_chunks",
    "submit_artifact",
    "request_human_review",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return load_json(SKILLS_ROOT / "manifest.json")


@pytest.fixture(scope="module")
def schema_registry() -> Registry[Any]:
    registry: Registry[Any] = Registry()
    for path in SKILLS_ROOT.rglob("*.schema.json"):
        schema = load_json(path)
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def skill_records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records = manifest["skills"]
    assert isinstance(records, list)
    return records


def test_manifest_declares_six_least_privilege_skills(manifest: dict[str, Any]) -> None:
    records = skill_records(manifest)
    assert {record["name"] for record in records} == {
        "plan-research",
        "collect-sources",
        "triage-sources",
        "analyze-source",
        "synthesize-topic",
        "verify-evidence",
    }
    for record in records:
        assert record["version"] == "1.0.0"
        assert set(record["allowed_tools"]) <= KNOWN_TOOLS


def test_every_skill_package_is_complete(manifest: dict[str, Any]) -> None:
    for record in skill_records(manifest):
        skill_dir = SKILLS_ROOT / record["name"]
        missing = {name for name in REQUIRED_FILES if not (skill_dir / name).is_file()}
        assert not missing, f"{record['name']} is missing {sorted(missing)}"

        instructions = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert instructions.isascii(), f"{record['name']} must remain readable by Pi on Windows"
        assert f"name: {record['name']}" in instructions
        assert f'version: "{record["version"]}"' in instructions
        for tool in record["allowed_tools"]:
            assert f"`{tool}`" in instructions


def test_examples_satisfy_input_and_output_contracts(
    manifest: dict[str, Any], schema_registry: Registry[Any]
) -> None:
    for record in skill_records(manifest):
        skill_dir = SKILLS_ROOT / record["name"]
        case = load_json(skill_dir / "examples" / "case.json")
        input_schema = load_json(skill_dir / "input.schema.json")
        output_schema = load_json(skill_dir / "output.schema.json")
        Draft202012Validator(input_schema, registry=schema_registry).validate(case["input"])
        Draft202012Validator(output_schema, registry=schema_registry).validate(case["output"])

        output = case["output"]
        assert output["skill"] == {"name": record["name"], "version": record["version"]}
        supported_ids = {
            evidence_id
            for item in output["evidence"]
            if item["disposition"] == "supported"
            for evidence_id in item["evidence_ids"]
        }
        assert set(output["evidence_ids"]) == supported_ids


def test_plan_example_stops_at_confirmation_gate(manifest: dict[str, Any]) -> None:
    plan = load_json(SKILLS_ROOT / "plan-research" / "examples" / "case.json")["output"]
    assert plan["structured"]["review"] == {
        "gate": "plan_confirmation",
        "status": "pending",
    }


def test_collection_contract_rejects_unapproved_plan() -> None:
    schema = load_json(SKILLS_ROOT / "collect-sources" / "input.schema.json")
    case = load_json(SKILLS_ROOT / "collect-sources" / "examples" / "case.json")["input"]
    case["plan_review"]["status"] = "pending"

    assert list(Draft202012Validator(schema).iter_errors(case))


def test_supported_evidence_requires_a_chunk_anchor(schema_registry: Registry[Any]) -> None:
    schema = load_json(SKILLS_ROOT / "verify-evidence" / "output.schema.json")
    output = load_json(SKILLS_ROOT / "verify-evidence" / "examples" / "case.json")["output"]
    output["evidence"][0]["evidence_ids"] = []

    assert list(Draft202012Validator(schema, registry=schema_registry).iter_errors(output))
