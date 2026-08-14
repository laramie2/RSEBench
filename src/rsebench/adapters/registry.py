"""Load the pinned baseline adapter registry."""

from __future__ import annotations

from pathlib import Path

import yaml

from rsebench.adapters.contracts import AdapterRegistry, BaselineAdapterSpec


def load_adapter_registry(path: Path | str) -> AdapterRegistry:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    adapters = payload.get("adapters", {})
    payload["adapters"] = {
        name: BaselineAdapterSpec(name=name, **spec)
        for name, spec in adapters.items()
    }
    registry = AdapterRegistry.model_validate(payload)
    if registry.version != 1:
        raise ValueError(f"unsupported adapter registry version: {registry.version}")
    return registry
