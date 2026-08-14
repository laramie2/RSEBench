import pytest

from rsebench.contracts import TaskManifest
from rsebench.noise.instruction import (
    FailedAttempt,
    RedundantContext,
    RelatedDistractor,
    _answer_leak_free,
)


@pytest.fixture
def task_fixture() -> TaskManifest:
    return TaskManifest(
        task_id="math-1",
        benchmark="dapo_fixed_1000",
        domain="math",
        prompt="Solve x + 1 = 3.",
        gold_answers=["2"],
        source_hash="a" * 64,
    )


def test_failed_attempt_is_deterministic_and_keeps_original_objective(task_fixture):
    op = FailedAttempt(model=None)
    a = op.generate(task_fixture, severity="L1", seed=7)
    b = op.generate(task_fixture, severity="L1", seed=7)
    assert a.payload == b.payload
    assert task_fixture.prompt in a.payload["prompt"]
    assert "失败" in a.payload["prompt"] or "尝试" in a.payload["prompt"]
    assert a.validation.accepted


@pytest.mark.parametrize("operator", [RedundantContext(), RelatedDistractor()])
def test_instruction_noise_records_cross_domain_taxonomy(operator, task_fixture):
    result = operator.generate(task_fixture, severity="L2", seed=11)
    assert result.manifest.channel.value == "C1"
    assert result.manifest.mechanism.value in {"M1", "M2"}
    assert result.manifest.severity.level.value == "L2"
    assert result.payload["original_prompt"] == task_fixture.prompt


def test_rule_addition_must_not_leak_gold_answer(task_fixture):
    result = FailedAttempt(model=None).generate(task_fixture, severity="L3", seed=2)
    assert task_fixture.gold_answers[0] not in result.payload["addition"]
    assert result.validation.answer_leak_free


def test_answer_leak_gate_ignores_quote_and_punctuation_variants():
    assert not _answer_leak_free(
        "Maybe it is 'Seasons in the Sun'?", ['"Seasons In The Sun"']
    )
