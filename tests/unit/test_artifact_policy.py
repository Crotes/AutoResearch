from __future__ import annotations

from datetime import UTC, datetime

import pytest

from autoresearch.adapters.sqlite import SqliteResearchLibrary
from autoresearch.application.artifact_policy import PolicyEnforcingArtifacts, PolicyViolationError
from autoresearch.domain import (
    AccessPolicy,
    ArtifactKind,
    ArtifactSubmission,
    ResearchPlan,
    ResearchProject,
    ResearchRun,
    ReviewDecision,
    ReviewKind,
    ReviewOutcome,
    RunStatus,
    SourceDocument,
    SourceKind,
    SourceRef,
    SourceVersion,
    Work,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)

SELECTED = ("work-w1", "work-w2")
EVIDENCE = {"work-w1": "sv-1#chunk-1", "work-w2": "sv-2#chunk-1", "work-w3": "sv-3#chunk-1"}


def analysis_submission(work_id: str) -> ArtifactSubmission:
    return ArtifactSubmission(
        kind=ArtifactKind.ANALYSIS,
        work_id=work_id,
        markdown="Analysis body",
        structured={
            "work_id": work_id,
            "research_problem": "How agents improve",
            "method": "Iterative feedback",
            "experiments": "A fixed benchmark",
            "results": "Improved success",
            "limitations": ["Small evaluation"],
            "applicability": "Tool-using agents",
            "reproducibility": "Code available",
            "relation_to_question": "Direct evidence",
        },
        evidence_ids=(EVIDENCE[work_id],),
        warnings=(),
        skill_name="analyze-source",
        skill_version="1.0.0",
    )


def synthesis_submission(evidence_ids: tuple[str, ...]) -> ArtifactSubmission:
    return ArtifactSubmission(
        kind=ArtifactKind.SYNTHESIS,
        work_id=None,
        markdown="Synthesis body",
        structured={
            "categories": [
                {"name": "reflection", "origin": "emergent", "work_ids": list(SELECTED)}
            ],
            "method_comparison": ["Feedback differs in timing"],
            "consensus": ["Evaluation matters"],
            "conflicts": [],
            "evidence_gaps": ["Long-term evidence"],
            "research_gaps": ["Stable adaptation"],
            "follow_up_questions": ["How should feedback be weighted?"],
        },
        evidence_ids=evidence_ids,
        warnings=(),
        skill_name="synthesize-topic",
        skill_version="1.0.0",
    )


def overview_submission() -> ArtifactSubmission:
    return ArtifactSubmission(
        kind=ArtifactKind.OVERVIEW,
        work_id="work-w1",
        markdown="Overview body",
        structured={
            "work_id": "work-w1",
            "title": "Self refining agents",
            "conclusion": "The method uses iterative feedback.",
            "relation": "Directly studies agent self-improvement.",
            "canonical_url": "https://arxiv.org/abs/1",
            "tags": ["agent"],
            "scores": {
                "relevance": 5,
                "credibility": 4,
                "evidence_strength": 4,
                "novelty": 3,
                "timeliness": 4,
                "reproducibility": 3,
                "potential_value": 5,
            },
            "recommendation": "select",
        },
        evidence_ids=("sv-1#chunk-1",),
        warnings=(),
        skill_name="triage-sources",
        skill_version="1.0.0",
    )


def seed(tmp_path) -> SqliteResearchLibrary:
    library = SqliteResearchLibrary(tmp_path / "library.sqlite", tmp_path / "content")
    library.save_project(ResearchProject("project-1", "Lab"))
    library.save_run(
        ResearchRun(
            id="run-1",
            project_id="project-1",
            status=RunStatus.RUNNING,
            plan=ResearchPlan(question="q", include_terms=("agent",)),
            workflow_version="w1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    for index, work_id in enumerate(("work-w1", "work-w2", "work-w3"), start=1):
        library.save_work(Work(work_id, f"Title {work_id}"))
        library.save_source(
            SourceDocument(
                source_version=SourceVersion(
                    id=f"sv-{index}",
                    work_id=work_id,
                    source_ref=SourceRef(SourceKind.ARXIV, f"arxiv:{index}"),
                    canonical_url=f"https://arxiv.org/abs/{index}",
                    retrieved_at=NOW,
                    content_hash=f"{index}".rjust(64, "a"),
                    access_policy=AccessPolicy.PERSIST,
                ),
                media_type="text/plain",
                text="first paragraph\nsecond paragraph",
                chunks=("first paragraph", "second paragraph"),
            )
        )
    return library


def approve_selection(library: SqliteResearchLibrary, work_ids: tuple[str, ...]) -> None:
    library.add_review(
        ReviewDecision(
            id="review-source",
            run_id="run-1",
            kind=ReviewKind.SOURCE,
            outcome=ReviewOutcome.APPROVED,
            reviewer="human",
            comment="",
            created_at=NOW,
            work_ids=work_ids,
        )
    )


def make_enforcer(library: SqliteResearchLibrary) -> PolicyEnforcingArtifacts:
    return PolicyEnforcingArtifacts(library)


def test_analysis_before_selection_is_rejected(tmp_path) -> None:
    library = seed(tmp_path)
    enforcer = make_enforcer(library)

    with pytest.raises(PolicyViolationError, match="approved source selection"):
        enforcer.submit_idempotent("run-1", "a-1", analysis_submission("work-w1"))


def test_analysis_only_accepts_approved_work_ids(tmp_path) -> None:
    library = seed(tmp_path)
    approve_selection(library, SELECTED)
    enforcer = make_enforcer(library)

    with pytest.raises(PolicyViolationError, match="work-w3"):
        enforcer.submit_idempotent("run-1", "a-w3", analysis_submission("work-w3"))

    accepted = enforcer.submit_idempotent("run-1", "a-w1", analysis_submission("work-w1"))
    assert accepted[0].submission.work_id == "work-w1"


def test_synthesis_requires_analyses_for_every_selected_work(tmp_path) -> None:
    library = seed(tmp_path)
    approve_selection(library, SELECTED)
    enforcer = make_enforcer(library)

    with pytest.raises(PolicyViolationError, match="missing analyses"):
        enforcer.submit_idempotent(
            "run-1", "s-incomplete", synthesis_submission((EVIDENCE["work-w1"],))
        )


def test_synthesis_rejects_evidence_outside_selected_works(tmp_path) -> None:
    library = seed(tmp_path)
    approve_selection(library, SELECTED)
    enforcer = make_enforcer(library)
    enforcer.submit_idempotent("run-1", "a-w1", analysis_submission("work-w1"))
    enforcer.submit_idempotent("run-1", "a-w2", analysis_submission("work-w2"))

    with pytest.raises(PolicyViolationError, match="outside the selected works"):
        enforcer.submit_idempotent(
            "run-1", "s-outside", synthesis_submission((EVIDENCE["work-w1"], EVIDENCE["work-w3"]))
        )


def test_synthesis_accepts_legal_evidence(tmp_path) -> None:
    library = seed(tmp_path)
    approve_selection(library, SELECTED)
    enforcer = make_enforcer(library)
    enforcer.submit_idempotent("run-1", "a-w1", analysis_submission("work-w1"))
    enforcer.submit_idempotent("run-1", "a-w2", analysis_submission("work-w2"))

    artifact, replay = enforcer.submit_idempotent(
        "run-1", "s-legal", synthesis_submission((EVIDENCE["work-w1"], EVIDENCE["work-w2"]))
    )

    assert replay is False
    assert artifact.submission.kind is ArtifactKind.SYNTHESIS


def test_overview_requires_running_collection_phase(tmp_path) -> None:
    library = seed(tmp_path)
    enforcer = make_enforcer(library)

    accepted = enforcer.submit_idempotent("run-1", "ov-1", overview_submission())
    assert accepted[0].submission.kind is ArtifactKind.OVERVIEW

    run = library.get_run("run-1")
    library.save_run(
        ResearchRun(
            id=run.id,
            project_id=run.project_id,
            status=RunStatus.REVIEW_REQUIRED,
            plan=run.plan,
            workflow_version=run.workflow_version,
            created_at=run.created_at,
            updated_at=NOW,
            checkpoint="overviews_ready",
        )
    )

    with pytest.raises(PolicyViolationError, match="only allowed during initial collection"):
        enforcer.submit_idempotent("run-1", "ov-2", overview_submission())


def test_policy_violation_error_is_a_value_error(tmp_path) -> None:
    library = seed(tmp_path)
    enforcer = make_enforcer(library)

    with pytest.raises(ValueError):
        enforcer.submit("run-1", analysis_submission("work-w1"))
