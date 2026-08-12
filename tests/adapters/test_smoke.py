import json
from pathlib import Path

from rsebench.adapters.contracts import (
    BaselineAdapterSpec,
    SmokeLevel,
    SmokeLevelRecord,
)
from rsebench.adapters.smoke import run_smoke


def _spec() -> BaselineAdapterSpec:
    return BaselineAdapterSpec(
        name="fixture",
        upstream_commit="a" * 40,
        method_path="fixture",
        launcher="scripts/baselines/smoke_fixture.py",
        model="deepseek-v4-flash",
        roles=["target"],
        native_domains=["fixture"],
    )


def test_smoke_stops_after_first_failed_level(tmp_path: Path):
    invoked = []

    def runner(spec, level, run_dir):
        invoked.append(level)
        return SmokeLevelRecord(
            level=level,
            status="failed" if level == SmokeLevel.structured else "passed",
            detail="fixture",
        )

    record = run_smoke(
        _spec(),
        through=SmokeLevel.evolution,
        output_root=tmp_path,
        level_runner=runner,
    )

    assert invoked == [SmokeLevel.transport, SmokeLevel.structured]
    assert record.status == "failed"
    assert json.loads(Path(record.run_dir, "summary.json").read_text())["status"] == "failed"


def test_smoke_runs_through_requested_level(tmp_path: Path):
    def runner(spec, level, run_dir):
        return SmokeLevelRecord(level=level, status="passed", evidence={"ok": True})

    record = run_smoke(
        _spec(),
        through=SmokeLevel.tool,
        output_root=tmp_path,
        level_runner=runner,
    )

    assert [item.level for item in record.levels] == [
        SmokeLevel.transport,
        SmokeLevel.structured,
        SmokeLevel.tool,
    ]
    assert record.status == "passed"
