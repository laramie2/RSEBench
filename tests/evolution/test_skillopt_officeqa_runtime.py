from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


METHOD_ROOT = Path(
    "/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt"
)
_added_method_root = str(METHOD_ROOT) not in sys.path
if _added_method_root:
    sys.path.insert(0, str(METHOD_ROOT))
try:
    from skillopt.envs.officeqa import rollout as officeqa_rollout  # noqa: E402
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


def test_officeqa_strict_recovery_round_withholds_tool_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeToolCall:
        id = "call-1"
        function = SimpleNamespace(
            name="grep",
            arguments='{"pattern":"value","path":"report.txt"}',
        )

        def model_dump(self, *, mode: str) -> dict:
            assert mode == "json"
            return {
                "id": self.id,
                "type": "function",
                "function": {
                    "name": self.function.name,
                    "arguments": self.function.arguments,
                },
            }

    responses = iter(
        [
            SimpleNamespace(content="", tool_calls=[FakeToolCall()], metadata={}),
            SimpleNamespace(
                content="I should inspect more evidence.",
                tool_calls=[],
                metadata={},
            ),
            SimpleNamespace(content="<answer>42</answer>", tool_calls=[], metadata={}),
        ]
    )
    calls: list[dict] = []

    def fake_chat_target_messages(**kwargs):
        calls.append(kwargs)
        return next(responses), {}

    monkeypatch.setattr(
        officeqa_rollout,
        "chat_target_messages",
        fake_chat_target_messages,
    )
    monkeypatch.setattr(officeqa_rollout, "is_target_exec_backend", lambda: False)
    monkeypatch.setattr(
        officeqa_rollout,
        "resolve_docs_roots",
        lambda _: [str(tmp_path)],
    )
    monkeypatch.setattr(
        officeqa_rollout,
        "resolve_candidate_files",
        lambda *_: [],
    )
    monkeypatch.setattr(
        officeqa_rollout,
        "build_oracle_parsed_pages_context",
        lambda *_args, **_kwargs: "oracle evidence",
    )
    monkeypatch.setattr(
        officeqa_rollout,
        "run_tool",
        lambda *_args, **_kwargs: ("grep(value, report.txt)", "42"),
    )

    result = officeqa_rollout.process_one(
        {
            "id": "q1",
            "question": "What is the value?",
            "ground_truth": "42",
            "source_files": ["report.txt"],
            "source_docs": ["https://example.test?page=1"],
        },
        str(tmp_path / "out"),
        "Return an answer.",
        max_tool_turns=3,
        data_dirs=[str(tmp_path)],
    )

    assert result["hard"] == 1
    assert len(calls) == 3
    assert calls[0]["tools"]
    assert calls[1]["tools"]
    assert not calls[2].get("tools")
