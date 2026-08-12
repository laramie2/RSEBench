"""Command-line entry points for reproducible benchmark construction."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from rsebench.contracts import NoiseManifest, TaskManifest
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
    }
    for name, schema in schemas.items():
        path = output_dir / name
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        typer.echo(path)


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


if __name__ == "__main__":
    app()
