"""Command-line entry points for reproducible benchmark construction."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from rsebench.contracts import NoiseManifest, TaskManifest
from rsebench.evidence import (
    FeedbackRecord,
    RuntimeNoiseSpec,
    TrajectoryRecord,
    read_record,
    write_record,
)
from rsebench.evidence.operators import mutate_record
from rsebench.adapters.contracts import SmokeLevel
from rsebench.adapters.registry import load_adapter_registry
from rsebench.adapters.smoke import run_smoke
from rsebench.experiments import run_math_execution_pilot
from rsebench.experiments.bootstrap import (
    bootstrap_registered_baselines,
    verify_registered_baselines,
)
from rsebench.experiments.preflight import (
    load_experiment_matrix,
    preflight_matrix,
)
from rsebench.experiments.release import (
    freeze_clean_release,
    normalize_release_aggregate,
)
from rsebench.experiments.scheduler import ExperimentScheduler
from rsebench.generation import generate_from_profile
from rsebench.providers.deepseek import DeepSeekClient
from rsebench.registry import validate_registries
from rsebench.selection.contracts import (
    ConfirmationSplit,
    SelectionReleaseManifest,
    StableSplitCandidate,
)
from rsebench.selection.release import (
    freeze_selection_release_roots,
)


app = typer.Typer(no_args_is_help=True)
baselines_app = typer.Typer(no_args_is_help=True)
experiment_app = typer.Typer(no_args_is_help=True)
release_app = typer.Typer(no_args_is_help=True)
selection_app = typer.Typer(no_args_is_help=True)
app.add_typer(baselines_app, name="baselines")
app.add_typer(experiment_app, name="experiment")
app.add_typer(release_app, name="release")
app.add_typer(selection_app, name="selection")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPERIMENT_MATRIX = ROOT / "configs/experiments/clean-v2.yaml"


@app.command("export-schemas")
def export_schemas(output_dir: Path = ROOT / "benchmark" / "schemas") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    schemas = {
        "task-manifest.schema.json": TaskManifest.model_json_schema(),
        "noise-manifest.schema.json": NoiseManifest.model_json_schema(),
        "trajectory-record.schema.json": TrajectoryRecord.model_json_schema(),
        "feedback-record.schema.json": FeedbackRecord.model_json_schema(),
        "runtime-noise-spec.schema.json": RuntimeNoiseSpec.model_json_schema(),
        "stable-split-candidate.schema.json": StableSplitCandidate.model_json_schema(),
        "confirmation-split.schema.json": ConfirmationSplit.model_json_schema(),
        "selection-release-manifest.schema.json": (
            SelectionReleaseManifest.model_json_schema()
        ),
    }
    for name, schema in schemas.items():
        path = output_dir / name
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        typer.echo(path)


@app.command("evidence-mutate")
def evidence_mutate(
    spec_path: Path = typer.Option(
        ..., "--spec", exists=True, dir_okay=False, readable=True
    ),
    input_path: Path = typer.Option(
        ..., "--input", exists=True, dir_okay=False, readable=True
    ),
    output_path: Path = typer.Option(..., "--output", dir_okay=False),
    audit_path: Path = typer.Option(..., "--audit", dir_okay=False),
    trajectory_path: Path | None = typer.Option(
        None, "--trajectory", exists=True, dir_okay=False, readable=True
    ),
) -> None:
    """Mutate a normalized N3/N4 record and write its audit record."""

    spec = RuntimeNoiseSpec.model_validate_json(
        spec_path.read_text(encoding="utf-8")
    )
    record = read_record(input_path)
    trajectory = read_record(trajectory_path) if trajectory_path else None
    if trajectory is not None and not isinstance(trajectory, TrajectoryRecord):
        raise typer.BadParameter("--trajectory must contain a trajectory record")
    result = mutate_record(record, spec, trajectory=trajectory)
    write_record(output_path, result.output_record)
    write_record(audit_path, result.audit)
    typer.echo(
        f"stage={spec.stage.value} applicable={result.audit.applicable} "
        f"output={output_path}"
    )


@app.command("registry-check")
def registry_check(registry_dir: Path = ROOT / "benchmark" / "registry") -> None:
    validate_registries(registry_dir)
    typer.echo("registry_valid")


@app.command("provider-check")
def provider_check(config: Path = ROOT / "configs" / "pilot" / "deepseek-v4-flash.yaml") -> None:
    client = DeepSeekClient.from_yaml(config)
    if not client.has_credentials():
        typer.echo("credentials_missing: set DEEPSEEK_API_KEY in .env")
        raise typer.Exit(code=2)
    typer.echo(f"provider_ready model={client.config.model}")


@app.command("generate-noise")
def generate_noise(
    profile: Path = typer.Option(..., exists=True, dir_okay=False),
    limit: int | None = typer.Option(None, min=1),
    offline: bool = typer.Option(False, help="Disable every model-backed generator."),
) -> None:
    summary = generate_from_profile(profile, limit=limit, offline=offline)
    typer.echo(
        f"status={summary.status} model={summary.model} counts={summary.counts}"
    )
    typer.echo(summary.run_dir)


@app.command("math-pilot-a")
def math_pilot_a(limit: int = typer.Option(5, min=1, max=20)) -> None:
    summary = run_math_execution_pilot(limit=limit)
    typer.echo(
        f"status={summary['status']} model={summary['model']} run={summary['run_dir']}"
    )


@app.command("baseline-smoke")
def baseline_smoke(
    method: str = typer.Option(...),
    through: SmokeLevel = typer.Option(SmokeLevel.transport),
) -> None:
    registry = load_adapter_registry(ROOT / "benchmark/registry/adapters.yaml")
    if method not in registry.adapters:
        raise typer.BadParameter(f"unknown baseline adapter: {method}")
    summary = run_smoke(
        registry.adapters[method],
        through=through,
        output_root=ROOT / "outputs/runs/baseline-smoke",
    )
    typer.echo(
        f"status={summary.status} method={summary.method} run={summary.run_dir}"
    )


def _configured_methods_root() -> Path:
    configured = os.environ.get("RSEBENCH_METHODS_ROOT")
    return Path(configured).resolve() if configured else ROOT / "methods/external"


@baselines_app.command("verify")
def baselines_verify() -> None:
    """Verify pinned baseline revisions and ordered patch fingerprints."""

    fingerprints = verify_registered_baselines(
        project_root=ROOT,
        methods_root=_configured_methods_root(),
    )
    for name, fingerprint in sorted(fingerprints.items()):
        typer.echo(f"{name} {fingerprint.fingerprint}")
    typer.echo(f"verified={len(fingerprints)}")


@baselines_app.command("bootstrap")
def baselines_bootstrap() -> None:
    """Clone missing pinned baselines and replay only registered patches."""

    fingerprints = bootstrap_registered_baselines(
        project_root=ROOT,
        methods_root=_configured_methods_root(),
    )
    for name, fingerprint in sorted(fingerprints.items()):
        typer.echo(f"{name} {fingerprint.fingerprint}")
    typer.echo(f"bootstrapped={len(fingerprints)}")


@experiment_app.command("preflight")
def experiment_preflight(
    matrix: Path = typer.Option(
        DEFAULT_EXPERIMENT_MATRIX,
        "--matrix",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Validate and expand a matrix without making provider calls."""

    report = preflight_matrix(matrix)
    for unit in report.units:
        typer.echo(f"{unit.key} {unit.identity.experiment_id}")
    typer.echo(
        f"units={len(report.units)} provider_calls={report.provider_calls} "
        f"all_ready={str(report.all_ready).lower()}"
    )


@experiment_app.command("run")
def experiment_run(
    matrix: Path = typer.Option(
        DEFAULT_EXPERIMENT_MATRIX,
        "--matrix",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    max_parallel: int = typer.Option(4, "--max-parallel", min=1),
    confirm_provider_cost: bool = typer.Option(False, "--confirm-provider-cost"),
    max_new_units: int | None = typer.Option(None, "--max-new-units", min=1),
) -> None:
    """Run a provider-backed matrix only after explicit cost confirmation."""

    if not confirm_provider_cost:
        typer.echo("refusing provider-backed run without --confirm-provider-cost")
        raise typer.Exit(code=2)
    report = preflight_matrix(matrix)
    scheduler = ExperimentScheduler(
        run_root=Path(report.output_root),
        project_root=ROOT,
        max_parallel=max_parallel,
        status_metadata={
            "matrix_path": report.matrix_path,
            "matrix_hash": report.matrix_hash,
            "git_head": report.repository_commit,
            "expected_units": len(report.units),
        },
    )
    rows = scheduler.run(
        [unit.scheduled for unit in report.units],
        max_new_units=max_new_units,
    )
    counts: dict[str, int] = {}
    for row in rows:
        state = str(row["state"])
        counts[state] = counts.get(state, 0) + 1
    typer.echo(f"run_root={report.output_root} states={json.dumps(counts, sort_keys=True)}")


def _matrix_output_root(matrix_path: Path) -> Path:
    matrix = load_experiment_matrix(matrix_path)
    output = Path(matrix.output_root)
    return output.resolve() if output.is_absolute() else (ROOT / output).resolve()


@experiment_app.command("status")
def experiment_status(
    matrix: Path = typer.Option(
        DEFAULT_EXPERIMENT_MATRIX,
        "--matrix",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Summarize scheduler state without changing it."""

    status_path = _matrix_output_root(matrix) / "matrix_status.json"
    if not status_path.is_file():
        typer.echo(f"status_missing={status_path}")
        raise typer.Exit(code=1)
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for row in payload.get("units", {}).values():
        state = str(row.get("state", "unknown"))
        counts[state] = counts.get(state, 0) + 1
    expected = payload.get("metadata", {}).get("expected_units", 0)
    typer.echo(f"expected_units={expected} states={json.dumps(counts, sort_keys=True)}")


@experiment_app.command("aggregate")
def experiment_aggregate(
    matrix: Path = typer.Option(
        DEFAULT_EXPERIMENT_MATRIX,
        "--matrix",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    output: Path | None = typer.Option(None, "--output", dir_okay=False),
) -> None:
    """Aggregate the fixed-denominator clean results under a matrix run root."""

    from scripts.aggregate_clean_qualification import build_aggregate

    run_root = _matrix_output_root(matrix)
    target = output or run_root / "aggregate.json"
    payload = build_aggregate(run_root, matrix=load_experiment_matrix(matrix))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    typer.echo(target)


@release_app.command("freeze")
def release_freeze(
    run_id: str = typer.Option(..., "--run-id"),
    matrix: Path = typer.Option(
        DEFAULT_EXPERIMENT_MATRIX,
        "--matrix",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Freeze an efficacy-ready run into an immutable compact release."""

    run_root = ROOT / "outputs/runs" / run_id
    aggregate_path = run_root / "aggregate.json"
    if not aggregate_path.is_file():
        raise typer.BadParameter(f"aggregate is missing: {aggregate_path}")
    matrix_contract = load_experiment_matrix(matrix)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    normalized = normalize_release_aggregate(aggregate, matrix_contract)
    baseline_names = list(
        dict.fromkeys(cell.baseline for cell in matrix_contract.cells)
    )
    fingerprints = verify_registered_baselines(
        project_root=ROOT,
        methods_root=_configured_methods_root(),
        names=baseline_names,
    )
    frozen = freeze_clean_release(
        run_root=run_root,
        aggregate_path=normalized,
        release_root=ROOT / "releases/clean-v2",
        run_id=run_id,
        baseline_fingerprints=fingerprints,
    )
    typer.echo(f"release_id={frozen.release_id}")
    typer.echo(frozen.path)


@selection_app.command("freeze")
def selection_freeze(
    selection_root: Path = typer.Option(
        ..., "--selection-root", exists=True, file_okay=False, readable=True
    ),
    run_root: Path = typer.Option(
        ..., "--run-root", exists=True, file_okay=False, readable=True
    ),
    release_root: Path = typer.Option(..., "--release-root", file_okay=False),
) -> None:
    """Freeze owned Task 8 selection/run roots without provider calls."""

    frozen = freeze_selection_release_roots(
        selection_root=selection_root,
        run_root=run_root,
        destination=release_root,
    )
    typer.echo(f"release_id={frozen.release_id} provider_calls=0")
    typer.echo(frozen.path)


if __name__ == "__main__":
    app()
