from __future__ import annotations

import json

from typer.testing import CliRunner

from rsebench.cli import app
from rsebench.evidence import (
    RuntimeNoiseSpec,
    TraceEvent,
    TrajectoryRecord,
    write_record,
)
from rsebench.evidence.operators import mutate_record


def test_evidence_mutate_cli_matches_direct_api(tmp_path) -> None:
    trajectory = TrajectoryRecord(
        task_id="task-1",
        benchmark="webshop",
        events=[
            TraceEvent(
                event_id="e0",
                step_index=0,
                kind="action",
                action="search[x]",
                tags=["query_refinement"],
            ),
            TraceEvent(
                event_id="e1",
                step_index=1,
                kind="action",
                action="click[y]",
                tags=["required_option"],
            ),
        ],
        reward=0.0,
        success=False,
    )
    spec = RuntimeNoiseSpec(
        stage="N3",
        operator="omit_critical_event",
        benchmark="webshop",
        domain="interactive",
        seed=7,
        selector="tag_priority",
        selector_parameters={"tags": ["required_option"]},
    )
    input_path = tmp_path / "input.json"
    spec_path = tmp_path / "spec.json"
    output_path = tmp_path / "output.json"
    audit_path = tmp_path / "audit.json"
    expected_path = tmp_path / "expected.json"
    write_record(input_path, trajectory)
    spec_path.write_text(
        json.dumps(spec.model_dump(mode="json")), encoding="utf-8"
    )
    write_record(expected_path, mutate_record(trajectory, spec).output_record)

    result = CliRunner().invoke(
        app,
        [
            "evidence-mutate",
            "--spec",
            str(spec_path),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--audit",
            str(audit_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_path.read_bytes() == expected_path.read_bytes()
    assert json.loads(audit_path.read_text())["selected_ids"] == ["e1"]


def test_export_schemas_includes_runtime_records(tmp_path) -> None:
    result = CliRunner().invoke(
        app, ["export-schemas", "--output-dir", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "trajectory-record.schema.json").exists()
    assert (tmp_path / "feedback-record.schema.json").exists()
    assert (tmp_path / "runtime-noise-spec.schema.json").exists()
