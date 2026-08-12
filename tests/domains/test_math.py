from rsebench.domains.math import (
    MathNoiseCandidate,
    generate_flawed_solution,
    scan_answer_leak,
    validate_flawed_solution,
    wrap_failed_attempt,
)
from rsebench.providers.deepseek import ModelResponse


def test_answer_leak_detects_normalized_ground_truth():
    assert scan_answer_leak(r"The result is \boxed{34}.", "34")
    assert scan_answer_leak("Answer: 1", "1")
    assert not scan_answer_leak("An intermediate coefficient is 1.", "1")
    assert not scan_answer_leak("A mistaken intermediate value is 3.", "34")


def test_wrapper_preserves_problem_and_marks_attempt_non_authoritative():
    prompt = wrap_failed_attempt("Find x.", "I divided by zero.")
    assert "Find x." in prompt
    assert "失败" in prompt or "可能有误" in prompt


def test_candidate_requires_two_critic_gates_and_no_leakage():
    candidate = MathNoiseCandidate(
        partial_solution="Assume the two events are independent, then multiply.",
        error_step="The independence assumption is unsupported.",
        error_type="invalid_independence",
        incorrect_conclusion="The requested probability is one half.",
        critic_error_present=True,
        critic_error_type="invalid_independence",
        critic_valid_proof=False,
    )
    report = validate_flawed_solution(candidate, gold_answer="3/4")
    assert report.accepted


def test_candidate_with_valid_proof_is_rejected():
    candidate = MathNoiseCandidate(
        partial_solution="A valid derivation.",
        error_step="claimed error",
        error_type="algebra",
        incorrect_conclusion="wrong",
        critic_error_present=True,
        critic_error_type="algebra",
        critic_valid_proof=True,
    )
    assert not validate_flawed_solution(candidate, gold_answer="7").accepted


def test_candidate_with_multiple_errors_is_rejected():
    candidate = MathNoiseCandidate(
        partial_solution="Use two unsupported transformations.",
        error_step="Both transformations are invalid.",
        error_type="algebra",
        incorrect_conclusion="wrong",
        critic_error_present=True,
        critic_error_type="algebra",
        critic_error_count=2,
        critic_valid_proof=False,
    )

    report = validate_flawed_solution(candidate, gold_answer="7")

    assert not report.accepted
    assert report.checks["exactly_one_error"] is False


def test_error_type_agreement_accepts_semantic_critic_paraphrase():
    candidate = MathNoiseCandidate(
        partial_solution="Apply a tangent-secant relation with the wrong product.",
        error_step="The tangent-secant theorem was misapplied.",
        error_type="Misapplication of the tangent-secant power theorem",
        incorrect_conclusion="The length is 9.",
        critic_error_present=True,
        critic_error_type=(
            "Incorrect application of tangent-secant theorem; "
            "the exterior and whole secant were confused."
        ),
        critic_valid_proof=False,
    )

    assert validate_flawed_solution(candidate, gold_answer="12").accepted


def test_generator_retries_empty_structured_response_before_critics():
    responses = iter(
        [
            "",
            '{"partial_solution":"Use an unsupported independence assumption.",'
            '"error_step":"Assume independence.",'
            '"error_type":"invalid independence",'
            '"incorrect_conclusion":"The probability is one half."}',
            '{"error_present":true,"error_step":"Assume independence.",'
            '"error_type":"invalid independence assumption","error_count":1}',
            '{"valid_proof":false,"reason":"The assumption is unsupported."}',
        ]
    )

    class FakeClient:
        def complete(self, messages, response_format, cache_key, role):
            return ModelResponse(content=next(responses))

    candidate = generate_flawed_solution(
        problem="Find the probability.",
        gold_answer="3/4",
        task_hash="c" * 64,
        client=FakeClient(),
        severity="L2",
        seed=3,
        max_attempts=2,
    )

    assert candidate.attempt_index == 1
    assert candidate.critic_error_count == 1
