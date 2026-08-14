"""Load the scheduler-owned formal identity inside a baseline launcher."""

from __future__ import annotations

import json
import os
from pathlib import Path

from rsebench.experiments.contracts import AttemptIdentity, ExperimentIdentity


def load_runtime_identity(
    *,
    required: bool,
    benchmark: str,
    method_seed: int,
) -> tuple[ExperimentIdentity | None, AttemptIdentity | None]:
    locator = os.environ.get("RSEBENCH_IDENTITY_PATH", "").strip()
    if not locator:
        if required:
            raise RuntimeError("formal experiment identity was not provided by scheduler")
        return None, None
    path = Path(locator).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"scheduler identity payload is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("scheduler identity payload must be an object")
    identity = ExperimentIdentity.model_validate(payload.get("identity"))
    attempt = AttemptIdentity.model_validate(payload.get("attempt"))
    if identity.experiment_id != attempt.experiment_id:
        raise ValueError("scheduler attempt belongs to a different experiment")
    if identity.inputs.benchmark != benchmark:
        raise ValueError("scheduler identity benchmark differs from launcher manifest")
    if identity.inputs.method_seed != method_seed:
        raise ValueError("scheduler identity method seed differs from launcher argument")
    expected = os.environ.get("RSEBENCH_EXPERIMENT_ID", "").strip()
    if expected and identity.experiment_id != expected:
        raise ValueError("scheduler experiment ID environment differs from payload")
    return identity, attempt


__all__ = ["load_runtime_identity"]
