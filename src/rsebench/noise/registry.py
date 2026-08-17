"""Deterministic discovery of independently owned N1-N4 packages."""

from __future__ import annotations

from pathlib import Path

import yaml

from rsebench.noise.contracts import NoisePlugin


_STAGE_ORDER = {"N1": 1, "N2": 2, "N3": 3, "N4": 4}


def _stages_root(root: Path) -> Path:
    canonical = root / "src/rsebench/noise/stages"
    return canonical if canonical.is_dir() else root


def discover_noise_plugins(project_root: Path | str) -> tuple[NoisePlugin, ...]:
    """Scan only stage package manifests; no shared Python registration list."""

    root = _stages_root(Path(project_root).resolve())
    plugins: list[NoisePlugin] = []
    for path in sorted(root.glob("*/plugin.yaml")):
        plugin = NoisePlugin.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )
        directory_stage = path.parent.name.upper()
        if plugin.stage != directory_stage:
            raise ValueError(
                f"noise plugin directory {path.parent.name} declares stage {plugin.stage}"
            )
        plugins.append(plugin)
    stages = tuple(plugin.stage for plugin in plugins)
    if set(stages) != set(_STAGE_ORDER) or len(stages) != 4:
        raise ValueError(f"noise plugins must declare N1-N4 exactly once: {stages}")
    entrypoints = tuple(plugin.entrypoint for plugin in plugins)
    if len(set(entrypoints)) != len(entrypoints):
        raise ValueError("noise plugin entrypoints must be unique")
    return tuple(sorted(plugins, key=lambda plugin: _STAGE_ORDER[plugin.stage]))


__all__ = ["discover_noise_plugins"]
