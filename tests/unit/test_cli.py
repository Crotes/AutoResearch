"""Black-box tests for the ``autoresearch`` CLI.

Every command is exercised through ``main(argv)`` with a Fake-backed
:class:`ResearchWorkflow`, so no Pi process or network is involved.
"""

from __future__ import annotations

import json

import pytest

import autoresearch.cli as cli
from autoresearch.adapters.fake import FakeRuntimeAdapter, InMemoryArtifactStore
from autoresearch.adapters.sqlite import SqliteResearchLibrary
from autoresearch.application.research import ResearchWorkflow
from autoresearch.domain import ReviewKind, ReviewOutcome, RunStatus


class CliHarness:
    def __init__(self, library: SqliteResearchLibrary) -> None:
        self.library = library
        self.store = InMemoryArtifactStore()

    def build(self, args: object) -> ResearchWorkflow:
        del args
        return ResearchWorkflow(
            self.library,
            self.library.content,
            lambda _: FakeRuntimeAdapter(artifacts=self.store),
        )


@pytest.fixture
def harness(tmp_path, monkeypatch) -> CliHarness:
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    instance = CliHarness(library)
    monkeypatch.setattr(cli, "_build_workflow", instance.build)
    return instance


def run(harness, capsys, argv: list[str]) -> tuple[int, str, str]:
    del harness
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _extract(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    raise AssertionError(f"{prefix!r} not found in {text!r}")


def start_run(harness, capsys) -> str:
    code, out, _ = run(
        harness,
        capsys,
        [
            "run",
            "start",
            "--project",
            "p1",
            "--question",
            "Agent 如何自进化?",
            "--include",
            "agent self-evolution",
        ],
    )
    assert code == 0
    return _extract(out, "run_id: ")


def test_project_create(harness, capsys) -> None:
    code, out, _ = run(
        harness, capsys, ["project", "create", "--name", "Agent evolution", "--description", "lab"]
    )

    assert code == 0
    assert "project_id:" in out
    project_id = _extract(out, "project_id: ")
    assert harness.library.get_project(project_id).name == "Agent evolution"


def test_run_start_reaches_source_gate(harness, capsys) -> None:
    code, out, _ = run(
        harness,
        capsys,
        [
            "run",
            "start",
            "--project",
            "p1",
            "--question",
            "Agent 如何自进化?",
            "--include",
            "agent self-evolution",
            "--include",
            "智能体 自进化",
        ],
    )

    assert code == 0
    run_id = _extract(out, "run_id: ")
    assert "run review" in out and "--select" in out
    persisted = harness.library.get_run(run_id)
    assert persisted.status is RunStatus.REVIEW_REQUIRED
    assert persisted.checkpoint == "overviews_ready"
    assert harness.library.list_events(run_id).events


def test_run_status(harness, capsys) -> None:
    run_id = start_run(harness, capsys)

    code, out, _ = run(harness, capsys, ["run", "status", run_id])

    assert code == 0
    assert "status: review_required" in out
    assert "overview:" in out
    assert "analysis:" in out
    assert "synthesis:" in out


def test_run_events(harness, capsys) -> None:
    run_id = start_run(harness, capsys)

    code, out, _ = run(harness, capsys, ["run", "events", run_id, "--cursor", "0"])

    assert code == 0
    page = harness.library.list_events(run_id, 0)
    lines = [line for line in out.splitlines() if line]
    assert len(lines) == len(page.events)
    for event, line in zip(page.events, lines, strict=True):
        assert str(event.sequence) in line


def test_run_review_selection(harness, capsys) -> None:
    run_id = start_run(harness, capsys)

    code, _, _ = run(
        harness,
        capsys,
        [
            "run",
            "review",
            run_id,
            "--select",
            "work-self-refine",
            "--select",
            "work-evolving-agent",
            "--reviewer",
            "alice",
        ],
    )

    assert code == 0
    source_reviews = [
        r for r in harness.library.list_reviews(run_id) if r.kind is ReviewKind.SOURCE
    ]
    assert source_reviews[-1].outcome is ReviewOutcome.APPROVED
    assert set(source_reviews[-1].work_ids) == {"work-self-refine", "work-evolving-agent"}


def test_run_review_final(harness, capsys) -> None:
    run_id = start_run(harness, capsys)
    run(
        harness,
        capsys,
        ["run", "review", run_id, "--select", "work-self-refine", "--reviewer", "alice"],
    )
    run(harness, capsys, ["run", "resume", run_id])

    code, _, _ = run(
        harness,
        capsys,
        ["run", "review", run_id, "--approve-final", "--reviewer", "alice"],
    )

    assert code == 0
    final_reviews = [r for r in harness.library.list_reviews(run_id) if r.kind is ReviewKind.FINAL]
    assert final_reviews[-1].outcome is ReviewOutcome.APPROVED


def test_run_resume_advances(harness, capsys) -> None:
    run_id = start_run(harness, capsys)
    run(
        harness,
        capsys,
        ["run", "review", run_id, "--select", "work-self-refine", "--reviewer", "alice"],
    )

    code, out, _ = run(harness, capsys, ["run", "resume", run_id])

    assert code == 0
    assert "status: review_required" in out
    persisted = harness.library.get_run(run_id)
    assert persisted.status is RunStatus.REVIEW_REQUIRED
    assert persisted.checkpoint == "analyses_ready"


def test_run_cancel_then_cancel_fails(harness, capsys) -> None:
    run_id = start_run(harness, capsys)

    code, _, _ = run(harness, capsys, ["run", "cancel", run_id])
    assert code == 0
    assert harness.library.get_run(run_id).status is RunStatus.CANCELLED

    code, _, err = run(harness, capsys, ["run", "cancel", run_id])
    assert code == 3
    assert "error:" in err
    assert "Traceback" not in err


def test_run_export(harness, capsys, tmp_path) -> None:
    run_id = start_run(harness, capsys)
    destination = tmp_path / "export"

    code, out, _ = run(harness, capsys, ["run", "export", run_id, "--output", str(destination)])

    assert code == 0
    assert "manifest_path:" in out
    assert (destination / "manifest.json").is_file()


def test_unknown_subcommand_exits_2(harness, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bogus"])
    assert excinfo.value.code == 2


def test_missing_required_parameter_exits_2(harness, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["project", "create"])
    assert excinfo.value.code == 2


@pytest.mark.parametrize("command", ["status", "events", "resume", "cancel"])
def test_unknown_run_id_exits_3(harness, capsys, command) -> None:
    code, _, err = run(harness, capsys, ["run", command, "run-does-not-exist"])

    assert code == 3
    assert "error:" in err
    assert "Traceback" not in err


def test_resume_without_selection_exits_3(harness, capsys) -> None:
    run_id = start_run(harness, capsys)

    code, _, err = run(harness, capsys, ["run", "resume", run_id])

    assert code == 3
    assert "error:" in err
    assert "Traceback" not in err


def test_json_outputs_are_parseable(harness, capsys) -> None:
    code, out, _ = run(
        harness,
        capsys,
        [
            "run",
            "start",
            "--project",
            "p1",
            "--question",
            "Agent 如何自进化?",
            "--include",
            "agent self-evolution",
            "--json",
        ],
    )
    assert code == 0
    started = json.loads(out)
    assert started["run_id"]
    assert started["status"] == "review_required"
    assert started["next_command"]

    run_id = started["run_id"]

    code, out, _ = run(harness, capsys, ["run", "status", run_id, "--json"])
    assert code == 0
    status = json.loads(out)
    assert status["status"] == "review_required"
    assert "overview" in status["artifacts"]

    code, out, _ = run(harness, capsys, ["run", "events", run_id, "--cursor", "0", "--json"])
    assert code == 0
    page = json.loads(out)
    assert "events" in page and "next_cursor" in page
    assert page["events"]


def test_demo_still_works(harness, capsys, tmp_path) -> None:
    code, out, _ = run(harness, capsys, ["demo", "--output", str(tmp_path / "demo")])

    assert code == 0
    assert "示例运行已完成" in out


def test_full_vertical_slice(harness, capsys, tmp_path) -> None:
    run_id = start_run(harness, capsys)
    run(
        harness,
        capsys,
        [
            "run",
            "review",
            run_id,
            "--select",
            "work-self-refine",
            "--select",
            "work-evolving-agent",
            "--reviewer",
            "alice",
        ],
    )
    run(harness, capsys, ["run", "resume", run_id])
    run(harness, capsys, ["run", "review", run_id, "--approve-final", "--reviewer", "alice"])

    code, _, _ = run(harness, capsys, ["run", "resume", run_id])
    assert code == 0
    assert harness.library.get_run(run_id).status is RunStatus.COMPLETED

    destination = tmp_path / "final-export"
    code, _, _ = run(harness, capsys, ["run", "export", run_id, "--output", str(destination)])
    assert code == 0
    assert (destination / "manifest.json").is_file()
