"""Baseline-facing evidence-noise hooks with replay-pack auditing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

from rsebench.evidence.contracts import (
    EvidenceStage,
    FeedbackRecord,
    HookContext,
    RuntimeNoiseSpec,
    TrajectoryRecord,
)
from rsebench.evidence.io import write_record
from rsebench.evidence.operators import mutate_record


class EvidenceAdapter(Protocol):
    """Convert a baseline's native objects at the two runtime boundaries."""

    def normalize_trajectory(
        self, native: Any, context: HookContext
    ) -> TrajectoryRecord: ...

    def denormalize_trajectory(
        self,
        native: Any,
        normalized: TrajectoryRecord,
        context: HookContext,
    ) -> Any: ...

    def normalize_feedback(
        self, native: Any, context: HookContext
    ) -> FeedbackRecord: ...

    def denormalize_feedback(
        self,
        native: Any,
        normalized: FeedbackRecord,
        context: HookContext,
    ) -> Any: ...


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return safe or "unnamed"


class EvidenceNoiseHook:
    """Apply configured N3/N4 mutations at stable baseline boundaries.

    An unconfigured stage is a true identity path: it avoids normalization and
    returns the exact native object. This makes a clean-arm installation safe.
    """

    def __init__(
        self,
        *,
        adapter: EvidenceAdapter,
        specs: dict[str | EvidenceStage, RuntimeNoiseSpec] | None = None,
    ) -> None:
        self.adapter = adapter
        self.specs: dict[EvidenceStage, RuntimeNoiseSpec] = {}
        for key, value in (specs or {}).items():
            stage = EvidenceStage(key)
            if stage != value.stage:
                raise ValueError(
                    f"runtime spec key {stage.value} does not match spec stage "
                    f"{value.stage.value}"
                )
            self.specs[stage] = value

    @classmethod
    def from_spec_files(
        cls,
        *,
        adapter: EvidenceAdapter,
        spec_paths: list[Path | str],
    ) -> "EvidenceNoiseHook":
        """Build a hook directly from fixed benchmark release artifacts."""

        specs: dict[EvidenceStage, RuntimeNoiseSpec] = {}
        for raw_path in spec_paths:
            path = Path(raw_path)
            spec = RuntimeNoiseSpec.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            if spec.stage in specs:
                raise ValueError(
                    f"duplicate runtime spec for stage {spec.stage.value}"
                )
            specs[spec.stage] = spec
        return cls(adapter=adapter, specs=specs)

    def _spec_for(
        self, stage: EvidenceStage, context: HookContext
    ) -> RuntimeNoiseSpec | None:
        # The same configured hook can safely be installed in both experiment
        # arms. Clean calls never normalize, mutate, or denormalize native data.
        if context.arm == "clean":
            return None
        spec = self.specs.get(stage)
        if spec is None:
            return None
        if spec.benchmark != context.benchmark:
            raise ValueError(
                "runtime spec benchmark mismatch: "
                f"{spec.benchmark!r} != {context.benchmark!r}"
            )
        if spec.domain != context.domain:
            raise ValueError(
                f"runtime spec domain mismatch: {spec.domain!r} != {context.domain!r}"
            )
        return spec

    def _write_replay(
        self,
        context: HookContext,
        stage: EvidenceStage,
        result: Any,
    ) -> Path:
        replay_dir = (
            context.run_dir
            / "mutation_audit"
            / context.arm
            / _safe_segment(context.task_id)
            / stage.value
        )
        write_record(replay_dir / "input.json", result.input_record)
        write_record(replay_dir / "output.json", result.output_record)
        write_record(replay_dir / "audit.json", result.audit)
        return replay_dir

    def after_rollout(self, native: Any, context: HookContext) -> Any:
        spec = self._spec_for(EvidenceStage.trajectory, context)
        if spec is None:
            return native
        normalized = self.adapter.normalize_trajectory(native, context)
        result = mutate_record(normalized, spec)
        self._write_replay(context, EvidenceStage.trajectory, result)
        return self.adapter.denormalize_trajectory(
            native, result.output_record, context
        )

    def after_feedback(
        self,
        native: Any,
        trajectory_native: Any,
        context: HookContext,
    ) -> Any:
        spec = self._spec_for(EvidenceStage.feedback, context)
        if spec is None:
            return native
        normalized = self.adapter.normalize_feedback(native, context)
        trajectory = self.adapter.normalize_trajectory(
            trajectory_native, context
        )
        result = mutate_record(normalized, spec, trajectory=trajectory)
        self._write_replay(context, EvidenceStage.feedback, result)
        return self.adapter.denormalize_feedback(
            native, result.output_record, context
        )
