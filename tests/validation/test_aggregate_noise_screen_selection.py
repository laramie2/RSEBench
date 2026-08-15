from __future__ import annotations

import importlib.util
from pathlib import Path

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
