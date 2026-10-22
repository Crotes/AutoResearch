from __future__ import annotations

from pathlib import Path

from autoresearch.application.identity import (
    IdentityCorrections,
    IdentitySignals,
    identity_key,
    resolve_work_id,
)

DOI = "10.1145/3610001.3610002"


def test_doi_beats_all_other_signals() -> None:
    signals = IdentitySignals(
        doi=f" {DOI.upper()} ",
        arxiv_id="2401.00001",
        repo_url="https://github.com/lab/repo",
        title="Something Else",
        first_author="Ada",
    )
    assert identity_key(signals) == f"doi:{DOI}"


def test_arxiv_id_strips_version_suffix() -> None:
    assert identity_key(IdentitySignals(arxiv_id="2401.00001v2")) == "arxiv:2401.00001"


def test_legacy_arxiv_ids_do_not_collapse_on_category_v() -> None:
    first = identity_key(IdentitySignals(arxiv_id="solv-int/9701001v2"))
    second = identity_key(IdentitySignals(arxiv_id="solv-int/9701002v1"))

    assert first == "arxiv:solv-int/9701001"
    assert second == "arxiv:solv-int/9701002"
    assert first != second


def test_repo_url_is_normalized() -> None:
    assert identity_key(IdentitySignals(repo_url="https://github.com/Lab/Repo.git/")) == (
        "repo:https://github.com/lab/repo"
    )


def test_title_and_author_fallback_is_normalized() -> None:
    left = IdentitySignals(title="Self-Refining  Language Agents!", first_author="Lovelace, Ada")
    right = IdentitySignals(title="self-refining language agents", first_author="lovelace ada")
    assert identity_key(left) == identity_key(right)


def test_resolution_is_deterministic() -> None:
    signals = IdentitySignals(arxiv_id="2401.00001")
    assert resolve_work_id(signals) == resolve_work_id(signals)
    assert resolve_work_id(signals).startswith("work-")


def test_preprint_paper_and_repo_share_one_work_via_doi() -> None:
    preprint = IdentitySignals(doi=DOI, arxiv_id="2401.00001")
    paper = IdentitySignals(doi=DOI, title="Self-Refining Language Agents", first_author="Ada")
    repo = IdentitySignals(doi=DOI, repo_url="https://github.com/lab/evolving-agent")
    works = {resolve_work_id(signals) for signals in (preprint, paper, repo)}
    assert len(works) == 1


def test_merge_correction_unites_heuristically_split_works(tmp_path: Path) -> None:
    preprint = IdentitySignals(arxiv_id="2401.00001")
    paper = IdentitySignals(title="Self-Refining Language Agents", first_author="Ada Lovelace")
    preprint_work = resolve_work_id(preprint)
    paper_work = resolve_work_id(paper)
    assert preprint_work != paper_work

    corrections = IdentityCorrections(tmp_path / "identity-corrections.jsonl")
    corrections.record_merge(source_work_id=paper_work, target_work_id=preprint_work)

    assert resolve_work_id(paper, corrections) == preprint_work
    assert resolve_work_id(preprint, corrections) == preprint_work

    reloaded = IdentityCorrections(tmp_path / "identity-corrections.jsonl")
    assert resolve_work_id(paper, reloaded) == preprint_work


def test_split_correction_separates_a_wrongly_merged_member(tmp_path: Path) -> None:
    signals = IdentitySignals(arxiv_id="2401.00001")
    work = resolve_work_id(signals)
    key = identity_key(signals)

    corrections = IdentityCorrections(tmp_path / "corrections.jsonl")
    corrections.record_split(work, member_key=key)

    assert resolve_work_id(signals, corrections) != work
    # other members of the same work are untouched
    other = IdentitySignals(doi=DOI)
    assert resolve_work_id(other, corrections) == resolve_work_id(other)
