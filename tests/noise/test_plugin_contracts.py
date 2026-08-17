from __future__ import annotations

import pytest

from rsebench.contracts import NoiseManifest, Severity
from rsebench.evidence import (
    EvidenceStage,
    RuntimeNoiseSpec,
    TraceEvent,
    TraceKind,
    TrajectoryRecord,
)
from rsebench.noise import NoisePlugin, RuntimeMutationOperator, StaticNoiseResult


HASH_A = "a" * 64
HASH_B = "b" * 64


def test_runtime_operator_cannot_register_for_static_stage() -> None:
    with pytest.raises(ValueError, match="runtime operator requires N3 or N4"):
        NoisePlugin(
            stage="N1",
            form="runtime",
            entrypoint="example:plugin",
            version="1",
            operators_root="example.operators",
        )


def test_legacy_noise_schemas_have_explicit_compatibility_versions() -> None:
    static = NoiseManifest(
        noise_id="t1-C1-M1-example-L2-s1",
        channel="C1",
        mechanism="M1",
        operator="example",
        domain="example",
        benchmark="example",
        severity=Severity(level="L2"),
        seed=1,
        clean_hash=HASH_A,
    )
    runtime = RuntimeNoiseSpec(
        stage="N3",
        operator="example",
        benchmark="example",
        domain="example",
        seed=1,
        selector="tag_priority",
    )

    assert static.schema_version == "rsebench.noise-manifest.v1"
    assert runtime.schema_version == "rsebench.runtime-noise-spec.v1"


def test_static_result_fails_closed_when_protected_audit_fails() -> None:
    with pytest.raises(ValueError, match="protected-field audit"):
        StaticNoiseResult(
            stage="N1",
            operator="example",
            version="1",
            task_id="t1",
            seed=7,
            applicable=True,
            clean_hash=HASH_A,
            noisy_hash=HASH_B,
            noisy_uri="rsebench-data://noisy/example/t1.json",
            protected_field_audit={"label_invariant": False},
            changes=("added one untrusted handover",),
        )


def test_runtime_bridge_preserves_existing_mutation_contract() -> None:
    record = TrajectoryRecord(
        task_id="t1",
        benchmark="example",
        events=[
            TraceEvent(
                event_id="e1",
                step_index=0,
                kind=TraceKind.tool,
                action="open",
                tags=["source_open"],
            ),
            TraceEvent(
                event_id="e2",
                step_index=1,
                kind=TraceKind.message,
                observation="done",
            ),
        ],
        reward=1.0,
        success=True,
    )
    spec = RuntimeNoiseSpec(
        stage=EvidenceStage.trajectory,
        operator="omit-source-open",
        benchmark="example",
        domain="example",
        seed=3,
        selector="tag_priority",
        selector_parameters={"tags": ["source_open"]},
        protected_fields=["reward", "success"],
    )

    result = RuntimeMutationOperator(stage="N3").mutate(record, spec)

    assert result.audit.applicable is True
    assert [event.event_id for event in result.output_record.events] == ["e2"]
    assert result.output_record.reward == 1.0
    assert result.output_record.success is True
