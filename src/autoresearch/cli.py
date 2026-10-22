"""Minimal CLI entry point for the contract bootstrap."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from autoresearch import __version__
from autoresearch.adapters import FakeRuntimeAdapter
from autoresearch.domain import ResearchPlan, RunSpec, SourceKind


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoresearch",
        description="Skill-first research collection and analysis.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")
    demo = subparsers.add_parser("demo", help="运行离线 Fake Adapter 纵向切片")
    demo.add_argument(
        "--output",
        type=Path,
        default=Path(".autoresearch/demo-export"),
        help="导出目录",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        return _run_demo(args.output)
    return 0


def _run_demo(output: Path) -> int:
    runtime = FakeRuntimeAdapter()
    spec = RunSpec(
        project_id="agent-self-evolution",
        plan=ResearchPlan(
            question="Agent 如何通过反馈实现自进化?",
            include_terms=("agent self-evolution", "智能体 自进化"),
            source_kinds=(SourceKind.ARXIV, SourceKind.GITHUB, SourceKind.RSS),
        ),
        workflow_version="fake-0.1.0",
        skill_versions={"triage-sources": "fake-0.1.0"},
        max_duration_seconds=300,
        max_candidates=20,
    )
    run_id = runtime.start(spec)
    overview_work_ids = tuple(
        artifact.submission.work_id
        for artifact in runtime.list_artifacts(run_id)
        if artifact.submission.work_id is not None
    )
    runtime.review_selection(run_id, overview_work_ids[:2])
    runtime.resume(run_id)
    runtime.review_final(run_id, approved=True)
    runtime.resume(run_id)
    runtime.export(run_id, output)
    print(f"示例运行已完成: {run_id}")
    print(f"导出目录: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
