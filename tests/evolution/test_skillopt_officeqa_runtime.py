from __future__ import annotations

import sys
from pathlib import Path

import pytest


METHOD_ROOT = Path(
    "/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt"
)
_added_method_root = str(METHOD_ROOT) not in sys.path
if _added_method_root:
    sys.path.insert(0, str(METHOD_ROOT))
try:
    from skillopt.envs.officeqa.rollout import (  # noqa: E402
        _officeqa_recovery_prompt,
        _parse_tool_arguments,
    )
finally:
    # Do not let the external repository's top-level ``scripts`` package
    # shadow this project's package during combined pytest collection.
    if _added_method_root:
        sys.path.remove(str(METHOD_ROOT))


def test_officeqa_tool_arguments_accept_literal_newline_inside_string() -> None:
    parsed = _parse_tool_arguments(
        '{"pattern":"1987\nOutlays","path":"report.txt"}'
    )

    assert parsed == {"pattern": "1987\nOutlays", "path": "report.txt"}


def test_officeqa_tool_arguments_still_reject_non_object_json() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        _parse_tool_arguments('["report.txt"]')


def test_officeqa_repeated_unstructured_response_forces_a_bounded_answer() -> None:
    first = _officeqa_recovery_prompt(turn=1)
    repeated = _officeqa_recovery_prompt(turn=2)

    assert "use a tool" in first
    assert "Stop repeating" in repeated
    assert "best-effort final answer" in repeated
    assert "<answer>...</answer>" in repeated
    assert "if more evidence" not in repeated
