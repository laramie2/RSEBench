from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_script():
    path = PROJECT_ROOT / "scripts/aggregate_noise_screen_selection.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_aggregate_parser_accepts_all_task8_root_modes() -> None:
    parser = _load_script().build_parser()
    for mode in ("reuse-audit", "qualification", "screening-generalization"):
        args = parser.parse_args(
            [
                "--selection-root",
                "selection",
                "--run-root",
                "runs",
                "--output",
                "out.json",
                "--mode",
                mode,
            ]
        )
        assert args.mode == mode
        assert args.selection_root == Path("selection")


def test_aggregate_parser_rejects_removed_synthetic_input_mode() -> None:
    parser = _load_script().build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--input", "synthetic.json", "--output", "out.json"])


def test_ready_qualification_writes_release_companion_from_owned_derivation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _load_script()
    selection_root = tmp_path / "selection"
    run_root = tmp_path / "runs"
    selection_root.mkdir()
    run_root.mkdir()
    output = run_root / "selection_status.json"
    status = SimpleNamespace(
        domains={
            benchmark: SimpleNamespace(
                next_action="freeze_candidate",
                selected_candidate_index=1,
            )
            for benchmark in (
                "spreadsheetbench_verified",
                "officeqa_full",
                "webshop",
                "skilllearnbench",
            )
        },
        model_dump_json=lambda indent: json.dumps({"domains": {}}, indent=indent),
    )
    companion = SimpleNamespace(
        model_dump_json=lambda indent: json.dumps(
            {"schema_version": "fixture", "companion_hash": "a" * 64},
            indent=indent,
        )
    )
    monkeypatch.setattr(script, "aggregate_from_roots", lambda **kwargs: status)
    monkeypatch.setattr(
        "rsebench.selection.qualification_io.derive_release_qualification_companion",
        lambda **kwargs: companion,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "aggregate_noise_screen_selection.py",
            "--selection-root",
            str(selection_root),
            "--run-root",
            str(run_root),
            "--output",
            str(output),
            "--mode",
            "qualification",
        ],
    )

    script.main()

    payload = json.loads((run_root / "release_qualification.json").read_text())
    assert payload["companion_hash"] == "a" * 64
