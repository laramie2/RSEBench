import json
from pathlib import Path

import pytest

import scripts.baselines.common_env as common_env
from scripts.baselines.common_env import deepseek_role_env, write_smoke_result


@pytest.mark.parametrize(
    ("method", "role", "expected"),
    [
        (
            "trace2skill",
            "executor",
            {
                "OPENAI_BASE_URL": "https://api.deepseek.com",
                "OPENAI_API_KEY": "fixture-key",
            },
        ),
        (
            "skillopt",
            "target",
            {
                "TARGET_OPENAI_COMPATIBLE_BASE_URL": "https://api.deepseek.com",
                "TARGET_OPENAI_COMPATIBLE_API_KEY": "fixture-key",
                "TARGET_OPENAI_COMPATIBLE_MODEL": "deepseek-v4-flash",
                "TARGET_OPENAI_COMPATIBLE_THINKING": "disabled",
            },
        ),
        (
            "skillgrad",
            "executor",
            {
                "AZURE_OPENAI_ENDPOINT": "https://api.deepseek.com",
                "AZURE_OPENAI_API_KEY": "fixture-key",
            },
        ),
        (
            "evoskill",
            "executor",
            {
                "DEEPSEEK_API_KEY": "fixture-key",
                "RSEBENCH_MODEL": "deepseek-v4-flash",
            },
        ),
        (
            "skills_coach",
            "optimizer",
            {
                "DEEPSEEK_API_KEY": "fixture-key",
                "RSEBENCH_MODEL": "deepseek-v4-flash",
            },
        ),
        (
            "federatedskill",
            "merger",
            {
                "DEEPSEEK_API_KEY": "fixture-key",
                "RSEBENCH_MODEL": "deepseek-v4-flash",
            },
        ),
    ],
)
def test_deepseek_role_env_maps_native_baseline_variables(method, role, expected):
    env = deepseek_role_env(method, role, api_key="fixture-key")

    assert env["RSEBENCH_MODEL"] == "deepseek-v4-flash"
    assert env["RSEBENCH_THINKING"] == "disabled"
    assert expected.items() <= env.items()


def test_deepseek_role_env_rejects_unknown_role():
    with pytest.raises(ValueError, match="unsupported role"):
        deepseek_role_env("skillopt", "merger", api_key="fixture-key")


def test_smoke_result_redacts_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-secret-key")

    path = write_smoke_result(
        tmp_path,
        method="trace2skill",
        level="transport",
        status="passed",
        detail="response used fixture-secret-key",
        evidence={"model": "deepseek-v4-flash"},
    )

    text = path.read_text(encoding="utf-8")
    assert "fixture-secret-key" not in text
    assert "[REDACTED]" in text
    assert json.loads(text)["model"] == "deepseek-v4-flash"


def test_credential_path_skips_empty_worktree_env(tmp_path: Path, monkeypatch):
    worktree = tmp_path / "worktree"
    checkout = tmp_path / "checkout"
    worktree.mkdir()
    (checkout / ".git").mkdir(parents=True)
    (worktree / ".env").write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")
    (checkout / ".env").write_text("DEEPSEEK_API_KEY=usable\n", encoding="utf-8")

    class Completed:
        stdout = str(checkout / ".git") + "\n"

    monkeypatch.setattr(common_env, "PROJECT_ROOT", worktree)
    monkeypatch.setattr(common_env.subprocess, "run", lambda *args, **kwargs: Completed())

    assert common_env._credential_env_path() == checkout / ".env"


def test_load_deepseek_key_replaces_inherited_empty_value(tmp_path: Path, monkeypatch):
    credential_file = tmp_path / ".env"
    credential_file.write_text(
        "DEEPSEEK_API_KEY=usable\nRSEBENCH_DATA_ROOT=/shared/data\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.delenv("RSEBENCH_DATA_ROOT", raising=False)
    monkeypatch.setattr(common_env, "_credential_env_path", lambda: credential_file)

    assert common_env.load_deepseek_key() == "usable"
    assert common_env.os.environ["DEEPSEEK_API_KEY"] == "usable"
    assert common_env.os.environ["RSEBENCH_DATA_ROOT"] == "/shared/data"
