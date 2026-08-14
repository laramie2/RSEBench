import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from rsebench.adapters.evoskill import (
    BridgeMessage,
    build_options,
    parse_response,
)


class Answer(BaseModel):
    final_answer: str


def test_build_options_locks_deepseek_and_preserves_schema(tmp_path):
    options = build_options(
        system="Be precise.",
        schema=Answer.model_json_schema(),
        tools=["Read", "Write"],
        project_root=tmp_path,
        model="deepseek-v4-flash",
    )

    assert options["sdk"] == "deepseek_api"
    assert options["model"] == "deepseek-v4-flash"
    assert options["schema"] == Answer.model_json_schema()
    assert options["working_directory"] == str(tmp_path.resolve())


def test_build_options_rejects_fallback_model(tmp_path):
    with pytest.raises(ValueError, match="deepseek-v4-flash"):
        build_options(
            system="",
            schema={},
            tools=[],
            project_root=tmp_path,
            model="gpt-5.5",
        )


def test_parse_response_returns_evoskill_trace_fields():
    raw = BridgeMessage(
        final_text=json.dumps({"final_answer": "42"}),
        turns=2,
        tool_calls=1,
        errors=[],
        duration_ms=12,
    )

    fields = parse_response([raw], Answer)

    assert fields["model"] == "deepseek-v4-flash"
    assert fields["output"].final_answer == "42"
    assert fields["is_error"] is False
    assert fields["num_turns"] == 2
    assert fields["messages"] == [raw]


def test_parse_response_records_schema_failure():
    raw = BridgeMessage(
        final_text="not-json",
        turns=1,
        tool_calls=0,
        errors=[],
        duration_ms=3,
    )

    fields = parse_response([raw], Answer)

    assert fields["output"] is None
    assert fields["is_error"] is True
    assert "JSON" in fields["parse_error"]
