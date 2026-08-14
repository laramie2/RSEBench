import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "aggregate_expanded_n1_results.py"


def test_aggregate_cli_collects_completed_and_gate_stopped_runs(tmp_path: Path):
    run_root = tmp_path / "runs"
    completed = run_root / "paired" / "spreadsheet" / "20260813T000000000000Z-skillopt"
    completed.mkdir(parents=True)
    (completed / "split_manifest.json").write_text("{}\n", encoding="utf-8")
    (completed / "result.json").write_text(
        json.dumps(
            {
                "method": "skillopt",
                "metrics": {
                    "seed_score": 0.3,
                    "clean_evolved_score": 0.5,
                    "noisy_evolved_score": 0.2,
                    "evolution_gap": 0.3,
                    "gap_ci_low": 0.1,
                    "gap_ci_high": 0.5,
                    "n_test": 20,
                },
            }
        ),
        encoding="utf-8",
    )
    stopped = run_root / "paired" / "officeqa" / "20260813T000001000000Z-skillopt"
    (stopped / "clean").mkdir(parents=True)
    (stopped / "split_manifest.json").write_text("{}\n", encoding="utf-8")
    (stopped / "clean" / "preflight.json").write_text(
        json.dumps({"passed": False, "artifact_updated": False}),
        encoding="utf-8",
    )
    output = tmp_path / "aggregate.json"

    subprocess.run(
        [sys.executable, str(SCRIPT), "--run-root", str(run_root), "--output", str(output)],
        cwd=PROJECT_ROOT,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run_summary"] == {
        "clean_gate_failed": 1,
        "completed": 1,
    }
    assert payload["domains"]["spreadsheet"]["positive_completed_runs"] == 1
    assert payload["domains"]["spreadsheet"]["ci_excludes_zero_runs"] == 1
    assert payload["token_usage"]["event_count"] == 0
