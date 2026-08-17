"""Generic attempt-local entrypoint for stage-owned validation cell runners."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path

from rsebench.noise import discover_noise_plugins
from rsebench.validation.contracts import ValidationCell


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    cell = ValidationCell.model_validate_json(args.cell.read_text(encoding="utf-8"))
    project_root = Path(__file__).resolve().parents[3]
    plugins = {plugin.stage: plugin for plugin in discover_noise_plugins(project_root)}
    module = importlib.import_module(plugins[cell.stage].operators_root)
    runners = getattr(module, "CELL_RUNNERS", {})
    runner = runners.get(cell.operator) if isinstance(runners, dict) else None
    if not callable(runner):
        raise RuntimeError(f"validation cell runner is not registered: {cell.operator}")
    result = runner(
        cell=cell,
        output_root=args.output_root,
        method_source=Path(os.environ["RSEBENCH_METHOD_SOURCE"]),
    )
    if not isinstance(result, dict):
        raise TypeError("validation cell runner must return a result mapping")
    result["identity"] = {"experiment_id": cell.identity_hash}
    destination = args.output_root / "result" / "result.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(destination.parent.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
