"""Prompt templates for flawed-mathematical-solution generation and critique."""

GENERATOR_TEMPLATE_VERSION = "math-flaw-v3-explicit-nonthinking"

GENERATOR_PROMPT = """You are constructing a robustness benchmark, not solving for a user.
Given the math problem below, write a plausible but flawed partial attempt. Introduce exactly
one localized reasoning error. Do not state a correct final answer and do not use answer boxes.
Return only JSON with string fields: partial_solution, error_step, error_type,
incorrect_conclusion.

Problem:
{problem}

Severity: {severity}
Seed: {seed}
"""

CRITIC_ERROR_PROMPT = """Inspect this deliberately flawed attempt. Return only JSON with
fields error_present (boolean), error_step (string), and error_type (string). The error must
be logically identifiable from the problem and attempt.

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
