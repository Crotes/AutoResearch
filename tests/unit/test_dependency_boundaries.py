from __future__ import annotations

import ast
from pathlib import Path


def test_application_does_not_import_adapters() -> None:
    application = Path(__file__).parents[2] / "src" / "autoresearch" / "application"
    violations: list[str] = []

    for path in application.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "autoresearch.adapters"
            ):
                violations.append(f"{path.relative_to(application)}:{node.lineno}")
            if isinstance(node, ast.Import):
                violations.extend(
                    f"{path.relative_to(application)}:{node.lineno}"
                    for alias in node.names
                    if alias.name.startswith("autoresearch.adapters")
                )

    assert violations == []
