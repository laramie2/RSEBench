from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rsebench.noise import discover_noise_plugins


ROOT = Path(__file__).resolve().parents[2]


def test_discovery_finds_exactly_one_stage_package_per_stage() -> None:
    plugins = discover_noise_plugins(ROOT)

    assert tuple(plugin.stage for plugin in plugins) == ("N1", "N2", "N3", "N4")
    assert tuple(plugin.form for plugin in plugins) == (
        "static",
        "static",
        "runtime",
        "runtime",
    )
    assert len({plugin.entrypoint for plugin in plugins}) == 4


def test_discovery_rejects_manifest_in_wrong_stage_directory(tmp_path: Path) -> None:
    stages = tmp_path / "src/rsebench/noise/stages"
    for stage in ("n1", "n2", "n3", "n4"):
        path = stages / stage / "plugin.yaml"
        path.parent.mkdir(parents=True)
        declared = "N2" if stage == "n1" else stage.upper()
        form = "static" if declared in {"N1", "N2"} else "runtime"
        path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "rsebench.noise-plugin.v1",
                    "stage": declared,
                    "form": form,
                    "entrypoint": f"example.{stage}:PLUGIN",
                    "version": "1",
                    "operators_root": f"example.{stage}.operators",
                }
            ),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="directory n1 declares stage N2"):
        discover_noise_plugins(tmp_path)
