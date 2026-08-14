"""Command-line entry points for reproducible benchmark construction."""

from __future__ import annotations

import json
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
from rsebench.generation import generate_from_profile
from rsebench.providers.deepseek import DeepSeekClient
from rsebench.registry import validate_registries


app = typer.Typer(no_args_is_help=True)
ROOT = Path(__file__).resolve().parents[2]


@app.command("export-schemas")
def export_schemas(output_dir: Path = ROOT / "benchmark" / "schemas") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    schemas = {
        "task-manifest.schema.json": TaskManifest.model_json_schema(),
        "noise-manifest.schema.json": NoiseManifest.model_json_schema(),
        "trajectory-record.schema.json": TrajectoryRecord.model_json_schema(),
        "feedback-record.schema.json": FeedbackRecord.model_json_schema(),
        "runtime-noise-spec.schema.json": RuntimeNoiseSpec.model_json_schema(),
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


if __name__ == "__main__":
    app()
