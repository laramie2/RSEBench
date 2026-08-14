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
    from skillopt.envs.officeqa.rollout import _parse_tool_arguments  # noqa: E402
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
