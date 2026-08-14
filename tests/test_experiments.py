import hashlib
from pathlib import Path

import pandas as pd

import rsebench.experiments as experiments
import rsebench.providers.deepseek as deepseek_provider
from rsebench.providers.deepseek import ModelResponse


def _prepare_project(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    project = tmp_path / "project"
    data = tmp_path / "data"
    outputs = tmp_path / "outputs"
    (project / "configs" / "pilot").mkdir(parents=True)
    (project / "configs" / "pilot" / "deepseek-v4-flash-generation.yaml").write_text(
        "provider: deepseek\n"
        "base_url: https://api.deepseek.com\n"
        "model: deepseek-v4-flash\n"
        "api_key_env: DEEPSEEK_API_KEY\n"
        "thinking: disabled\n"
        "max_tokens: 2048\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(experiments, "PROJECT_ROOT", project)
    monkeypatch.setattr(deepseek_provider, "PROJECT_ROOT", project)
    monkeypatch.setenv("RSEBENCH_DATA_ROOT", str(data))
    monkeypatch.setenv("RSEBENCH_OUTPUT_ROOT", str(outputs))
    return data, outputs


def _write_dapo(data: Path) -> None:
    target = data / "materialized" / "dapo_fixed_1000"
    target.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "normalized_problem_hash": "a" * 64,
                "prompt": [{"role": "user", "content": "Compute 2+2."}],
                "reward_model": {"ground_truth": "4"},
            }
        ]
    ).to_parquet(target / "dapo_fixed_1000.parquet")


def test_math_execution_pilot_records_missing_credentials_without_fallback(
    tmp_path: Path, monkeypatch
):
    _, _ = _prepare_project(tmp_path, monkeypatch)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    summary = experiments.run_math_execution_pilot(limit=1)

    assert summary["status"] == "blocked_on_credentials"
    assert summary["model"] == "deepseek-v4-flash"
    assert Path(summary["run_dir"], "summary.json").is_file()


def test_math_execution_pilot_scores_all_paired_conditions(tmp_path: Path, monkeypatch):
    data, _ = _prepare_project(tmp_path, monkeypatch)
    _write_dapo(data)

    class FakeClient:
        def has_credentials(self):
            return True

        def complete(self, messages, cache_key):
            assert messages[-1]["content"]
            assert cache_key
            return ModelResponse(
                content="Reasoning omitted.\nAnswer: \\boxed{4}",
                usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            )

    loaded_configs = []

    def fake_from_yaml(path, *args, **kwargs):
        loaded_configs.append(Path(path).name)
        return FakeClient()

    monkeypatch.setattr(experiments.DeepSeekClient, "from_yaml", fake_from_yaml)

    summary = experiments.run_math_execution_pilot(limit=1)

    assert summary["status"] == "experiment_complete"
    assert summary["usage"]["total_tokens"] == 12
    assert set(summary["rows"][0]["conditions"]) == {"L0", "L1", "L2", "L3"}
    assert all(
        condition["correct"]
        for condition in summary["rows"][0]["conditions"].values()
    )
    assert summary["decision"] is not None
    assert loaded_configs == ["deepseek-v4-flash-generation.yaml"]


def test_answer_parser_handles_plain_and_boxed_final_lines():
    assert experiments._answer_text("work\nAnswer: 12.") == "12"
    assert experiments._answer_text("work\nAnswer: \\boxed{7}") == "7"
    assert experiments._correct("Answer: 1,000", "1000")


def test_math_execution_cache_key_versions_the_non_thinking_profile():
    expected = hashlib.sha256(
        b"math-pilot-a-v2-nonthinking:task:execute:L0"
    ).hexdigest()
    assert experiments._cache_key("task", "execute", "L0") == expected
