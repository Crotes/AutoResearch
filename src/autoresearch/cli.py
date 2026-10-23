"""Command-line entry point for the research workflow.

The CLI is a thin input/display layer: every command delegates to
:class:`autoresearch.application.research.ResearchWorkflow` and only formats
results for humans (stdout) or machines (``--json``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from autoresearch import __version__
from autoresearch.adapters import FakeRuntimeAdapter, SqliteResearchLibrary
from autoresearch.adapters.mcp.wiring import (
    CONTENT_ROOT_ENV,
    DATABASE_ENV,
    MODE_ENV,
    RUN_ID_ENV,
    RUN_MODE,
    WiringError,
)
from autoresearch.adapters.pi import PiRuntimeAdapter
from autoresearch.application.artifact_policy import PolicyViolationError
from autoresearch.application.research import ResearchWorkflow, RunPersister
from autoresearch.application.workflow import InvalidTransitionError
from autoresearch.domain import (
    ArtifactKind,
    ResearchPlan,
    ResearchRun,
    RunSpec,
    RunStatus,
    SourceKind,
)
from autoresearch.ports.runtime import WorkerRuntime

_EXIT_OK = 0
_EXIT_USAGE = 2
_EXIT_NOT_FOUND = 3
_EXIT_RUN_FAILED = 4
_EXIT_INTERNAL = 5

_JSON = argparse.ArgumentParser(add_help=False)
_JSON.add_argument(
    "--json",
    action="store_true",
    default=argparse.SUPPRESS,
    help="输出机器可读 JSON 到 stdout",
)


class CliUsageError(ValueError):
    """Manual CLI parameter validation failed (exit code 2)."""


def _default_database() -> Path:
    return Path(os.environ.get(DATABASE_ENV, ".autoresearch/research.sqlite3"))


def _default_content_root() -> Path | None:
    value = os.environ.get(CONTENT_ROOT_ENV)
    return Path(value) if value else None


def _source_kind(value: str) -> SourceKind:
    lowered = value.strip().lower()
    for kind in SourceKind:
        if kind.name.lower() == lowered:
            return kind
    names = ", ".join(kind.name for kind in SourceKind)
    raise argparse.ArgumentTypeError(f"未知来源类型 {value!r}(可选: {names})")


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"期望整数: {value!r}") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return number


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"期望整数: {value!r}") from error
    if number < 0:
        raise argparse.ArgumentTypeError("必须为非负整数")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoresearch",
        description="Skill-first research collection and analysis.",
        parents=[_JSON],
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--database",
        type=Path,
        default=_default_database(),
        help="研究库 SQLite 路径(默认 $AUTORESEARCH_DATABASE 或 .autoresearch/research.sqlite3)",
    )
    parser.add_argument(
        "--content-root",
        type=Path,
        default=_default_content_root(),
        help="内容存储根目录(默认 $AUTORESEARCH_CONTENT_ROOT 或 <database>.content)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="运行离线 Fake Adapter 纵向切片", parents=[_JSON])
    demo.add_argument(
        "--output",
        type=Path,
        default=Path(".autoresearch/demo-export"),
        help="导出目录",
    )

    project = subparsers.add_parser("project", help="管理研究项目")
    project_sub = project.add_subparsers(dest="action", required=True)
    project_create = project_sub.add_parser("create", help="创建项目", parents=[_JSON])
    project_create.add_argument("--name", required=True, help="项目名称")
    project_create.add_argument("--description", default="", help="项目描述")

    run = subparsers.add_parser("run", help="管理研究运行")
    run_sub = run.add_subparsers(dest="action", required=True)

    start = run_sub.add_parser("start", help="开始一次研究运行", parents=[_JSON])
    start.add_argument("--project", required=True, help="项目 ID")
    start.add_argument("--question", required=True, help="研究问题")
    start.add_argument(
        "--include",
        action="extend",
        nargs="+",
        required=True,
        metavar="TERM",
        help="包含关键词(可重复)",
    )
    start.add_argument(
        "--exclude", action="extend", nargs="+", metavar="TERM", help="排除关键词(可重复)"
    )
    start.add_argument(
        "--source",
        action="extend",
        nargs="+",
        type=_source_kind,
        metavar="KIND",
        help="来源类型(arxiv/github/rss/manual_url,可重复)",
    )
    start.add_argument(
        "--language", action="extend", nargs="+", metavar="LANG", help="语言(默认 zh en)"
    )
    start.add_argument("--max-candidates", type=_positive_int, default=20, help="候选来源上限")
    start.add_argument("--max-duration", type=_positive_int, default=1800, help="时长预算(秒)")
    start.add_argument("--start-date", help="开始日期(YYYY-MM-DD)")
    start.add_argument("--end-date", help="结束日期(YYYY-MM-DD)")
    start.add_argument(
        "--seed-url", action="extend", nargs="+", metavar="URL", help="种子来源 URL(可重复)"
    )
    start.add_argument("--yes", action="store_true", help="跳过确认(当前无交互提示)")

    status = run_sub.add_parser("status", help="查看运行状态", parents=[_JSON])
    status.add_argument("run_id", help="运行 ID")

    events = run_sub.add_parser("events", help="查看运行事件", parents=[_JSON])
    events.add_argument("run_id", help="运行 ID")
    events.add_argument("--cursor", type=_non_negative_int, default=0, help="事件游标")

    review = run_sub.add_parser("review", help="记录人工审核", parents=[_JSON])
    review.add_argument("run_id", help="运行 ID")
    review_group = review.add_mutually_exclusive_group(required=True)
    review_group.add_argument(
        "--select", action="extend", nargs="+", metavar="WORK_ID", help="选中的成果(可重复)"
    )
    review_group.add_argument("--approve-final", action="store_true", help="终审通过")
    review_group.add_argument("--reject-final", action="store_true", help="终审驳回")
    review.add_argument("--reviewer", required=True, help="审核人")
    review.add_argument("--comment", default="", help="审核意见")

    resume = run_sub.add_parser("resume", help="恢复运行", parents=[_JSON])
    resume.add_argument("run_id", help="运行 ID")

    cancel = run_sub.add_parser("cancel", help="取消运行", parents=[_JSON])
    cancel.add_argument("run_id", help="运行 ID")

    export = run_sub.add_parser("export", help="导出运行", parents=[_JSON])
    export.add_argument("run_id", help="运行 ID")
    export.add_argument("--output", type=Path, help="导出目录(默认 .autoresearch/exports/<run_id>)")

    return parser


def _reconfigure_utf8(stream: object) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load repo-root `.env` into the process environment (existing vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main(argv: Sequence[str] | None = None) -> int:
    _load_dotenv()
    _reconfigure_utf8(sys.stdin)
    _reconfigure_utf8(sys.stdout)
    _reconfigure_utf8(sys.stderr)
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except CliUsageError as error:
        return _fail(str(error), _EXIT_USAGE)
    except (KeyError, InvalidTransitionError) as error:
        return _fail(str(error), _EXIT_NOT_FOUND)
    except (WiringError, PolicyViolationError) as error:
        return _fail(str(error), _EXIT_INTERNAL)
    except Exception as error:
        return _fail(str(error), _EXIT_INTERNAL)


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "demo":
        return _run_demo(args.output)
    workflow = _build_workflow(args)
    if args.command == "project" and args.action == "create":
        return _project_create(args, workflow)
    if args.command == "run":
        action = args.action
        if action == "start":
            return _run_start(args, workflow)
        if action == "status":
            return _run_status(args, workflow)
        if action == "events":
            return _run_events(args, workflow)
        if action == "review":
            return _run_review(args, workflow)
        if action == "resume":
            return _run_resume(args, workflow)
        if action == "cancel":
            return _run_cancel(args, workflow)
        if action == "export":
            return _run_export(args, workflow)
    return _EXIT_OK


def _build_workflow(
    args: argparse.Namespace,
    runtime_factory: Callable[[RunPersister], WorkerRuntime] | None = None,
) -> ResearchWorkflow:
    database = str(args.database)
    content_root = _resolve_content_root(database, args.content_root)
    library = SqliteResearchLibrary(database, content_root)
    if runtime_factory is None:
        runtime_factory = _pi_runtime_factory(database, content_root)
    return ResearchWorkflow(library, library.content, runtime_factory)


def _resolve_content_root(database: str, content_root: Path | None) -> str:
    return str(content_root) if content_root is not None else f"{database}.content"


def _pi_runtime_factory(
    database: str, content_root: str
) -> Callable[[RunPersister], PiRuntimeAdapter]:
    def run_env(run_id: str) -> dict[str, str]:
        return {
            RUN_ID_ENV: run_id,
            DATABASE_ENV: database,
            CONTENT_ROOT_ENV: content_root,
            MODE_ENV: RUN_MODE,
        }

    def factory(persist_run: RunPersister) -> PiRuntimeAdapter:
        return PiRuntimeAdapter(run_env=run_env, persist_run=persist_run)

    return factory


def _json_mode(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False))


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _fail(message: str, code: int) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def _project_create(args: argparse.Namespace, workflow: ResearchWorkflow) -> int:
    project = workflow.create_project(name=args.name, description=args.description)
    if _json_mode(args):
        _print_json(
            {
                "project_id": project.id,
                "name": project.name,
                "description": project.description,
            }
        )
    else:
        print(f"project_id: {project.id}")
        print(f"name: {project.name}")
    return _EXIT_OK


def _run_start(args: argparse.Namespace, workflow: ResearchWorkflow) -> int:
    question = str(args.question).strip()
    if not question:
        raise CliUsageError("--question 不能为空")
    include = tuple(args.include)
    if not include:
        raise CliUsageError("至少需要一个 --include")
    languages = tuple(args.language) if args.language else ("zh", "en")
    run = workflow.start_run(
        project_id=args.project,
        question=question,
        include=include,
        exclude=tuple(args.exclude or ()),
        source_kinds=tuple(args.source or ()),
        languages=languages,
        max_candidates=args.max_candidates,
        max_duration_seconds=args.max_duration,
        start_date=args.start_date,
        end_date=args.end_date,
        seed_urls=tuple(args.seed_url or ()),
    )
    _print_run_summary(run, _next_command(run), _json_mode(args))
    if run.status in (RunStatus.FAILED, RunStatus.CANCELLED):
        return _fail(f"run {run.id} ended in state {run.status}", _EXIT_RUN_FAILED)
    return _EXIT_OK


def _run_status(args: argparse.Namespace, workflow: ResearchWorkflow) -> int:
    view = workflow.status(args.run_id)
    counts = {str(kind): view.artifact_counts[kind] for kind in ArtifactKind}
    reviews = [
        {"kind": str(review.kind), "outcome": str(review.outcome), "reviewer": review.reviewer}
        for review in view.latest_reviews
    ]
    if _json_mode(args):
        _print_json(
            {
                "run_id": view.run.id,
                "status": str(view.run.status),
                "checkpoint": view.run.checkpoint,
                "artifacts": counts,
                "stale_artifacts": view.stale_artifact_count,
                "reviews": reviews,
                "warnings": list(view.warnings),
            }
        )
    else:
        print(f"run_id: {view.run.id}")
        print(f"status: {view.run.status}")
        print(f"checkpoint: {view.run.checkpoint}")
        print("artifacts:")
        for kind in ArtifactKind:
            print(f"  {kind}: {counts[str(kind)]}")
        print(f"stale_artifacts: {view.stale_artifact_count}")
        print("reviews:")
        for review in view.latest_reviews:
            print(f"  {review.kind} {review.outcome} by {review.reviewer}")
        print("warnings:")
        if view.warnings:
            for warning in view.warnings:
                print(f"  - {warning}")
        else:
            print("  (none)")
    return _EXIT_OK


def _run_events(args: argparse.Namespace, workflow: ResearchWorkflow) -> int:
    # The workflow's ``events`` method does not validate run existence, so call
    # ``status`` first to surface ``KeyError`` for unknown run ids (exit code 3).
    workflow.status(args.run_id)
    page = workflow.events(args.run_id, cursor=args.cursor)
    if _json_mode(args):
        _print_json(
            {
                "events": [
                    {
                        "sequence": event.sequence,
                        "occurred_at": event.occurred_at.isoformat(),
                        "kind": str(event.kind),
                        "data": event.data,
                    }
                    for event in page.events
                ],
                "next_cursor": page.next_cursor,
            }
        )
    else:
        for event in page.events:
            print(
                f"{event.sequence}\t{event.occurred_at.isoformat()}\t{event.kind}\t"
                f"{json.dumps(event.data, ensure_ascii=False, sort_keys=True)}"
            )
    return _EXIT_OK


def _run_review(args: argparse.Namespace, workflow: ResearchWorkflow) -> int:
    reviewer = str(args.reviewer).strip()
    if not reviewer:
        raise CliUsageError("--reviewer 不能为空")
    comment = args.comment or ""
    if args.select:
        decision = workflow.record_selection(
            args.run_id, work_ids=tuple(args.select), reviewer=reviewer, comment=comment
        )
    elif args.approve_final:
        decision = workflow.record_final_review(
            args.run_id, approved=True, reviewer=reviewer, comment=comment
        )
    else:
        decision = workflow.record_final_review(
            args.run_id, approved=False, reviewer=reviewer, comment=comment
        )
    payload = {
        "review_id": decision.id,
        "run_id": decision.run_id,
        "kind": str(decision.kind),
        "outcome": str(decision.outcome),
        "reviewer": decision.reviewer,
        "comment": decision.comment,
        "work_ids": list(decision.work_ids),
    }
    if _json_mode(args):
        _print_json(payload)
    else:
        print(f"review_id: {decision.id}")
        print(f"kind: {decision.kind}")
        print(f"outcome: {decision.outcome}")
        print(f"reviewer: {decision.reviewer}")
        if decision.work_ids:
            print("work_ids: " + ", ".join(decision.work_ids))
    return _EXIT_OK


def _run_resume(args: argparse.Namespace, workflow: ResearchWorkflow) -> int:
    run = workflow.resume_run(args.run_id)
    _print_run_summary(run, _next_command(run), _json_mode(args))
    if run.status in (RunStatus.FAILED, RunStatus.CANCELLED):
        return _fail(f"run {run.id} ended in state {run.status}", _EXIT_RUN_FAILED)
    return _EXIT_OK


def _run_cancel(args: argparse.Namespace, workflow: ResearchWorkflow) -> int:
    run = workflow.cancel_run(args.run_id)
    if _json_mode(args):
        _print_json({"run_id": run.id, "status": str(run.status), "checkpoint": run.checkpoint})
    else:
        print(f"run_id: {run.id}")
        print(f"status: {run.status}")
        print(f"checkpoint: {run.checkpoint}")
    return _EXIT_OK


def _run_export(args: argparse.Namespace, workflow: ResearchWorkflow) -> int:
    destination = args.output or Path(".autoresearch/exports") / args.run_id
    result = workflow.export_run(args.run_id, destination)
    if _json_mode(args):
        _print_json(
            {
                "destination": str(result.destination),
                "manifest_path": str(result.manifest_path),
                "artifact_count": result.artifact_count,
                "stale_artifact_count": result.stale_artifact_count,
                "warnings": list(result.warnings),
            }
        )
    else:
        print(f"destination: {result.destination}")
        print(f"manifest_path: {result.manifest_path}")
        print(f"artifact_count: {result.artifact_count}")
        print(f"stale_artifact_count: {result.stale_artifact_count}")
        print("warnings:")
        if result.warnings:
            for warning in result.warnings:
                print(f"  - {warning}")
        else:
            print("  (none)")
    return _EXIT_OK


def _print_run_summary(run: ResearchRun, next_command: str, json_mode: bool) -> None:
    if json_mode:
        _print_json(
            {
                "run_id": run.id,
                "status": str(run.status),
                "checkpoint": run.checkpoint,
                "next_command": next_command,
            }
        )
    else:
        print(f"run_id: {run.id}")
        print(f"status: {run.status}")
        print(f"checkpoint: {run.checkpoint}")
        print(f"next: {next_command}")


def _next_command(run: ResearchRun) -> str:
    run_id = run.id
    if run.status is RunStatus.REVIEW_REQUIRED and run.checkpoint == "overviews_ready":
        return f"autoresearch run review {run_id} --select WORK_ID ... --reviewer <reviewer>"
    if run.status is RunStatus.REVIEW_REQUIRED and run.checkpoint == "analyses_ready":
        return f"autoresearch run review {run_id} --approve-final --reviewer <reviewer>"
    if run.status is RunStatus.PAUSED:
        return f"autoresearch run resume {run_id}"
    if run.status is RunStatus.RUNNING:
        return f"autoresearch run status {run_id}"
    if run.status is RunStatus.COMPLETED:
        return f"autoresearch run export {run_id} --output .autoresearch/exports/{run_id}"
    return f"autoresearch run status {run_id}"


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
