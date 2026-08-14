from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_pilot_model_is_locked_to_deepseek_v4_flash():
    cfg = yaml.safe_load(
        (ROOT / "configs/pilot/deepseek-v4-flash.yaml").read_text()
    )
    assert cfg["provider"] == "deepseek"
    assert cfg["model"] == "deepseek-v4-flash"
    assert cfg["base_url"] == "https://api.deepseek.com"
    assert cfg["api_key_env"] == "DEEPSEEK_API_KEY"
    assert "gpt-5.5" not in str(cfg).lower()


def test_env_is_ignored_and_example_has_no_secret():
    assert ".env" in (ROOT / ".gitignore").read_text().splitlines()
    text = (ROOT / ".env.example").read_text()
    assert "DEEPSEEK_API_KEY=" in text
    assert not any(
        line.split("=", 1)[-1].strip()
        for line in text.splitlines()
        if "API_KEY=" in line
    )


def test_structured_math_generation_uses_non_thinking_flash_profile():
    math = yaml.safe_load((ROOT / "configs/pilot/math.yaml").read_text())
    profile = yaml.safe_load(
        (ROOT / "configs/pilot/deepseek-v4-flash-generation.yaml").read_text()
    )
    assert math["model_config"] == "configs/pilot/deepseek-v4-flash-generation.yaml"
    assert profile["model"] == "deepseek-v4-flash"
    assert profile["thinking"] == "disabled"
    assert profile["max_tokens"] <= 4096


def test_math_execution_pilot_uses_non_thinking_flash_profile():
    source = (ROOT / "src/rsebench/experiments.py").read_text()
    assert "deepseek-v4-flash-generation.yaml" in source
