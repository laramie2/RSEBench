"""Prompt templates for flawed-mathematical-solution generation and critique."""

GENERATOR_TEMPLATE_VERSION = "math-flaw-v4-short-single-error"

GENERATOR_PROMPT = """You are constructing a robustness benchmark, not solving for a user.
Given the math problem below, write a plausible but flawed partial attempt. Introduce exactly
one localized reasoning error. Stop immediately after that erroneous step; do not continue to
a final numeric or symbolic result, and do not explain or repair the error inside
partial_solution. Keep partial_solution under 140 words and every other string under 45 words.
The exact gold-answer token below is forbidden from every returned string. Do not repeat it,
even when describing what must be avoided. incorrect_conclusion must be a short qualitative
claim with no digits, fractions, answer boxes, or final requested expression.
Return only JSON with string fields: partial_solution, error_step, error_type,
incorrect_conclusion.

Problem:
{problem}

Forbidden gold-answer token (never copy into output):
{gold_answer}

Severity: {severity}
Seed: {seed}
"""

CRITIC_ERROR_PROMPT = """Inspect this deliberately flawed attempt. Return only JSON with
fields error_present (boolean), error_step (string), error_type (string), and error_count
(integer). Count logically independent reasoning errors, not downstream consequences of the
same localized error. The declared attempt is acceptable only when error_count is exactly 1.

Problem:
{problem}

Attempt:
{attempt}
"""

CRITIC_VALIDITY_PROMPT = """Independently judge whether the attempt is a valid proof or
solution. Return only JSON with fields valid_proof (boolean) and reason (string). Do not
complete the original problem.

Problem:
{problem}

Attempt:
{attempt}
"""
