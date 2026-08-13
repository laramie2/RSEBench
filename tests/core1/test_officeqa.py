from __future__ import annotations

from rsebench.core1.officeqa import (
    build_conflicting_period_fixture,
    build_officeqa_n1_pair,
    select_structurally_calibrated_tasks,
)
from rsebench.contracts import TaskManifest
from rsebench.domains.officeqa import (
    CorpusDocument,
    OfficeQATask,
    validate_officeqa_noise,
)


def office_task() -> OfficeQATask:
    return OfficeQATask(
        task_id="UID0001",
        question=(
            "What were the total expenditures (in millions of nominal dollars) "
            "for U.S national defense in the calendar year of 1940?"
        ),
        answers=["2,602"],
        gold_document_id="treasury_bulletin_1941_01.txt",
    )


def _manifest(
    task_id: str,
    question: str,
    *,
    difficulty: str = "easy",
    source_file_count: int = 1,
) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="officeqa_full",
        domain="document",
        prompt=question,
        gold_answers=["1"],
        source_hash="0" * 64,
        metadata={
            "difficulty": difficulty,
            "source_file_count": source_file_count,
        },
    )


def test_structural_calibration_prefers_easy_single_source_direct_lookup() -> None:
    tasks = [
        _manifest("hard", "What is the value?", difficulty="hard"),
        _manifest("multi", "What is the value?", source_file_count=2),
        _manifest(
            "stats",
            "Calculate the standard deviation and regression coefficient.",
        ),
        _manifest("direct", "What is the reported value?"),
    ]

    selected = select_structurally_calibrated_tasks(tasks, count=2)

    assert [task.task_id for task in selected] == ["direct", "stats"]


def test_structural_calibration_is_deterministic_and_does_not_read_predictions() -> None:
    first = _manifest("b", "What is the reported value?")
    second = _manifest("a", "What is the reported value?")

    selected = select_structurally_calibrated_tasks([first, second], count=2)

    assert [task.task_id for task in selected] == ["a", "b"]


def corpus() -> list[CorpusDocument]:
    return [
        CorpusDocument(
            document_id="treasury_bulletin_1941_01.txt",
            text=(
                "Calendar year 1940 national defense total expenditures, "
                "millions of nominal dollars."
            ),
        ),
        CorpusDocument(
            document_id="treasury_bulletin_1942_01.txt",
            text=(
                "Calendar year 1941 national defense total expenditures, "
                "millions of nominal dollars."
            ),
        ),
        CorpusDocument(
            document_id="treasury_bulletin_1943_01.txt",
            text=(
                "Fiscal year 1942 national defense total expenditures, "
                "millions of nominal dollars."
            ),
        ),
        CorpusDocument(
            document_id="treasury_bulletin_1944_01.txt",
            text="Calendar year 1943 postal revenue in thousands of dollars.",
        ),
    ]


def test_n1_changes_only_calendar_axis_and_excludes_answer() -> None:
    task = office_task()

    pair = build_officeqa_n1_pair(task, seed=11)

    assert pair.clean_question == task.question
    assert pair.noisy_question.startswith(task.question)
    assert pair.axis == "calendar_fiscal"
    assert pair.original == "calendar year"
    assert pair.replacement == "fiscal year"
    assert "2602" not in "".join(character for character in pair.noisy_question if character.isalnum())


def test_n2_uses_real_conflicting_period_source_and_keeps_gold_top3() -> None:
    task = office_task()

    fixture = build_conflicting_period_fixture(task, corpus(), seed=11)

    top3 = fixture.results[:3]
    assert len(top3) == 3
    assert sum(row.document_id == task.gold_document_id for row in top3) == 1
    decoys = [row for row in top3 if row.document_id != task.gold_document_id]
    assert decoys
    assert all(row.document_id in {doc.document_id for doc in corpus()} for row in decoys)
    assert any("1941" in row.text or "1942" in row.text for row in decoys)
    assert validate_officeqa_noise(task, fixture).accepted


def test_n2_is_deterministic_and_does_not_synthesize_documents() -> None:
    task = office_task()

    first = build_conflicting_period_fixture(task, corpus(), seed=3)
    second = build_conflicting_period_fixture(task, corpus(), seed=3)

    assert first == second
    source_texts = {doc.text for doc in corpus()}
    assert all(
        row.is_gold or row.text in source_texts
        for row in first.results
    )
