from pathlib import Path

import pytest

from rsebench.domains.officeqa import (
    CorpusDocument,
    OfficeQATask,
    build_corpus_index,
    build_rank_fixture,
    select_decoy_documents,
    validate_officeqa_noise,
)


@pytest.fixture
def officeqa_task() -> OfficeQATask:
    return OfficeQATask(
        task_id="UID0002",
        question="What were federal expenditures for the Veterans Administration?",
        answers=["507"],
        gold_document_id="treasury_bulletin_1944_01.txt",
    )


def test_rank_fixture_moves_but_never_removes_gold(officeqa_task):
    fixture = build_rank_fixture(
        officeqa_task, decoys=["decoy-a", "decoy-b"], gold_rank=3
    )
    assert fixture.results[2].document_id == officeqa_task.gold_document_id
    assert (
        sum(
            result.document_id == officeqa_task.gold_document_id
            for result in fixture.results
        )
        == 1
    )
    assert validate_officeqa_noise(officeqa_task, fixture).accepted


def test_decoy_selector_excludes_gold_duplicates_and_answer(tmp_path: Path, officeqa_task):
    (tmp_path / officeqa_task.gold_document_id).write_text(
        "Veterans Administration federal expenditures", encoding="utf-8"
    )
    (tmp_path / "good-decoy.txt").write_text(
        "Veterans Administration budget estimates for another period", encoding="utf-8"
    )
    (tmp_path / "leaky.txt").write_text(
        "Veterans Administration expenditure was 507", encoding="utf-8"
    )
    documents = build_corpus_index(tmp_path)
    decoys = select_decoy_documents(officeqa_task, documents, limit=5)
    assert [document.document_id for document in decoys] == ["good-decoy.txt"]


def test_rank_fixture_requires_enough_unique_decoys(officeqa_task):
    with pytest.raises(ValueError, match="decoys"):
        build_rank_fixture(officeqa_task, decoys=[CorpusDocument(document_id="d", text="x")], gold_rank=3)
