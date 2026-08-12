from rsebench.domains.math import (
    MathNoiseCandidate,
    scan_answer_leak,
    validate_flawed_solution,
    wrap_failed_attempt,
)


def test_answer_leak_detects_normalized_ground_truth():
    assert scan_answer_leak(r"The result is \boxed{34}.", "34")
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
