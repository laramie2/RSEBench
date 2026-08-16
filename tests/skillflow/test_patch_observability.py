from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from rsebench.usage import aggregate_token_usage


ROOT = Path(__file__).resolve().parents[2]
METHOD_ROOT = ROOT / "methods/external/skillflow"
EXTERNAL_PYTHON = METHOD_ROOT / ".venv/bin/python"


pytestmark = pytest.mark.skipif(
    not EXTERNAL_PYTHON.is_file(),
    reason="SkillFlow native environment is not bootstrapped",
)


@pytest.mark.parametrize(
    "runner_name",
    ["family_job_runner.py", "iterative_shared_skills_runner.py"],
)
def test_native_runners_use_the_current_async_harbor_factory(
    runner_name: str,
) -> None:
    source = (METHOD_ROOT / runner_name).read_text(encoding="utf-8")

    assert "await Job.create(group_config)" in source
    assert "Job(config=group_config)" not in source


def test_native_deepseek_agent_accepts_the_frozen_worker_token_budget() -> None:
    source = (
        METHOD_ROOT / "libs/harbor_noinstall_agents/deepseek_api.py"
    ).read_text(encoding="utf-8")

    assert 'self.max_tokens = int(kwargs.pop("max_tokens", 2048))' in source
    assert "max_tokens=self.max_tokens" in source


def test_native_deepseek_agent_explicitly_discovers_mounted_skills() -> None:
    source = (
        METHOD_ROOT / "libs/harbor_noinstall_agents/deepseek_api.py"
    ).read_text(encoding="utf-8")

    assert "/root/.agents/skills" in source
    assert "SKILL.md" in source


def _run_native(script: str, *args: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "src"), str(METHOD_ROOT), environment.get("PYTHONPATH", ""))
    )
    return subprocess.run(
        [str(EXTERNAL_PYTHON), "-c", script, *(str(arg) for arg in args)],
        cwd=METHOD_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_native_litellm_records_success_and_error_attempts(tmp_path: Path) -> None:
    script = r'''
import sys
from pathlib import Path

from libs.terminus_agent.llms import lite_llm as module

success_dir = Path(sys.argv[1])
error_dir = Path(sys.argv[2])

def configure(ledger):
    import os
    os.environ.update({
        "RSEBENCH_TOKEN_LEDGER_DIR": str(ledger),
        "RSEBENCH_TOKEN_RUN_ID": "patch-test",
        "RSEBENCH_TOKEN_DOMAIN": "skill_native",
        "RSEBENCH_TOKEN_BENCHMARK": "skillflow_tasks",
        "RSEBENCH_TOKEN_ARM": "clean_evolution",
        "RSEBENCH_TOKEN_STAGE": "worker_and_patcher",
    })

llm = module.LiteLLM(
    model_name="openai/deepseek-v4-flash",
    temperature=0.2,
    api_base="https://api.deepseek.com/v1",
    api_key="test-key",
)

configure(success_dir)
module.litellm.completion = lambda **kwargs: {
    "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
}
assert llm.call(prompt="patch", message_history=[]) == "{}"

configure(error_dir)
def fail(**kwargs):
    raise RuntimeError("provider down")
module.litellm.completion = fail
try:
    module.LiteLLM.call.__wrapped__(llm, prompt="patch", message_history=[])
except RuntimeError:
    pass
else:
    raise AssertionError("error call did not raise")
'''
    success = tmp_path / "success"
    error = tmp_path / "error"
    completed = _run_native(script, success, error)

    assert completed.returncode == 0, completed.stderr
    success_summary = aggregate_token_usage(success)
    error_summary = aggregate_token_usage(error)
    assert success_summary["attempted_calls"] == 1
    assert success_summary["observed_coverage"] == 1.0
    assert success_summary["billed_tokens"]["total_tokens"] == 14
    assert success_summary["groups"]["stage"]["patcher"]["attempted_calls"] == 1
    assert error_summary["attempted_calls"] == 1
    assert error_summary["failed_calls"] == 1
    assert error_summary["observed_coverage"] == 0.0


def test_patch_failure_still_appends_timing_history(tmp_path: Path) -> None:
    script = r'''
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from iterative_shared_skills_runner import run_patch_operation_with_history

history = Path(sys.argv[1])
utc_values = iter([
    datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 8, 16, 10, 0, 3, tzinfo=timezone.utc),
])
monotonic_values = iter([10.0, 12.5])

def fail():
    raise RuntimeError("patch failed")

try:
    run_patch_operation_with_history(
        fail,
        history_path=history,
        base_entry={"task_name": "task-1", "trial_name": "trial-1"},
        utc_now=lambda: next(utc_values),
        monotonic=lambda: next(monotonic_values),
    )
except RuntimeError:
    pass
else:
    raise AssertionError("patch operation did not raise")

print(history.read_text())
'''
    history = tmp_path / "skill_patch_history.jsonl"
    completed = _run_native(script, history)

    assert completed.returncode == 0, completed.stderr
    row = json.loads(history.read_text(encoding="utf-8"))
    assert row["task_name"] == "task-1"
    assert row["started_at"] == "2026-08-16T10:00:00+00:00"
    assert row["ended_at"] == "2026-08-16T10:00:03+00:00"
    assert row["duration_seconds"] == 2.5
    assert row["status"] == "failed"
    assert row["error_type"] == "RuntimeError"
