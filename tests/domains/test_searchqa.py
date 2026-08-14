from rsebench.contracts import TaskManifest
from rsebench.domains.searchqa import (
    SearchQADecoyCandidate,
    inject_semantic_decoy_evidence,
)


def _task() -> TaskManifest:
    return TaskManifest(
        task_id="q1",
        benchmark="searchqa_skillopt",
        domain="document",
        prompt="Who wrote the report?",
        gold_answers=["Ada Lovelace"],
        source_hash="a" * 64,
        metadata={"context": "[DOC] [TLE] Report [PAR] Ada Lovelace wrote it."},
    )


def test_searchqa_decoy_preserves_gold_evidence_and_prepends_false_evidence():
    result = inject_semantic_decoy_evidence(
        _task(),
        SearchQADecoyCandidate(
            decoy_passages=[
                "[TLE] Archived index [PAR] The report is attributed to Grace Hopper.",
                "[TLE] Community note [PAR] Grace Hopper appears as the author.",
            ]
        ),
        severity="L2",
        seed=7,
    )

    assert result.noisy_context.startswith("[DOC] [TLE] Archived index")
    assert _task().metadata["context"] in result.noisy_context
    assert result.validation.accepted
    assert result.validation.checks["decoy_count"] == 2


def test_searchqa_decoy_rejects_gold_answer_leak():
    result = inject_semantic_decoy_evidence(
        _task(),
        SearchQADecoyCandidate(
            decoy_passages=["[TLE] Note [PAR] It was Ada Lovelace."]
        ),
        severity="L1",
        seed=7,
    )

    assert not result.validation.answer_leak_free
    assert not result.validation.accepted


def test_searchqa_decoy_rejects_numeric_word_answer_alias():
    task = _task().model_copy(update={"gold_answers": ["5"]})
    result = inject_semantic_decoy_evidence(
        task,
        SearchQADecoyCandidate(
            decoy_passages=["[TLE] Note [PAR] The insect has five eyes."]
        ),
        severity="L1",
        seed=7,
    )

    assert not result.validation.answer_leak_free
