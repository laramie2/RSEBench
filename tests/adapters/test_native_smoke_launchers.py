import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "method",
    [
        "trace2skill",
        "skillopt",
        "skillgrad",
        "evoskill",
        "skills_coach",
        "skillflow",
        "federatedskill",
    ],
)
@pytest.mark.parametrize("level", ["transport", "structured", "tool"])
def test_native_smoke_launcher_writes_fixture_result(tmp_path: Path, method, level):
    output = tmp_path / method / level
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / f"scripts/baselines/smoke_{method}.py"),
            "--level",
            level,
            "--output",
            str(output),
            "--offline-fixture",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["model"] == "deepseek-v4-flash"
    assert result["evidence"]["offline_fixture"] is True


def test_skillopt_tool_smoke_uses_compat_message_attributes():
    source = (ROOT / "scripts/baselines/smoke_skillopt.py").read_text(
        encoding="utf-8"
    )

    assert "message.tool_calls[0]" in source
    assert "call.function.name" in source
