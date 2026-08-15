from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    path = PROJECT_ROOT / "scripts/run_noise_screen_replays.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_task8_root_cli_dry_plan_has_zero_provider_calls(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    calls = []

    def fake_plan(**kwargs):
        calls.append(kwargs)
        return {
            "schema_version": "rsebench.noise-screen-replay-matrix.v1",
            "evaluation_role": "qualification_test",
            "commands": [["python", "replay.py"]],
            "jobs": [{"benchmark": "officeqa_full"}],
            "provider_calls": 0,
        }

    monkeypatch.setattr(module, "build_root_replay_plan", fake_plan)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dry root plan must not execute subprocesses")
        ),
    )
    run_root = tmp_path / "runs"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--selection-root",
            str(tmp_path / "selection"),
            "--run-root",
            str(run_root),
            "--evaluation-role",
            "qualification_test",
            "--candidate-index",
            "2",
            "--repeats",
            "3",
            "--resume",
        ],
    )

    module.main()

    output = run_root / "replay_plans/qualification_test-candidate-2-r3.json"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["provider_calls"] == 0
    assert calls[0]["candidate_index"] == 2
    assert calls[0]["resume"] is True


def test_root_cli_execute_still_requires_explicit_cost_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module,
        "build_root_replay_plan",
        lambda **_kwargs: {
            "schema_version": "rsebench.noise-screen-replay-matrix.v1",
            "commands": [],
            "jobs": [],
            "provider_calls": 0,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            module.__file__,
            "--selection-root",
            str(tmp_path / "selection"),
            "--run-root",
            str(tmp_path / "runs"),
            "--evaluation-role",
            "screening_test",
            "--repeats",
            "3",
            "--execute",
        ],
    )

    try:
        module.main()
    except ValueError as exc:
        assert "--confirm-provider-cost" in str(exc)
    else:
        raise AssertionError("execute without cost confirmation was accepted")
