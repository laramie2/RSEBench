from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

from rsebench import cli
from rsebench.selection import ConfirmationSplit, StableSplitCandidate
from rsebench.selection.contracts import SelectionReleaseManifest
from scripts.freeze_noise_screen_selection import main


def _release_test_module() -> ModuleType:
    path = Path(__file__).parents[1] / "selection/test_release.py"
    spec = importlib.util.spec_from_file_location("release_test_fixtures", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load release fixtures: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE_FIXTURES = _release_test_module()
DOMAINS = RELEASE_FIXTURES.DOMAINS


runner = CliRunner()


@pytest.fixture
def release_input_file(tmp_path: Path) -> Path:
    release_inputs = RELEASE_FIXTURES.make_release_inputs()
    payload = {
        key: (
            {name: value.model_dump(mode="json") for name, value in field.items()}
            if key in {"candidates", "confirmations", "decisions"}
            else field.model_dump(mode="json")
            if hasattr(field, "model_dump")
            else field
        )
        for key, field in release_inputs.items()
    }
    path = tmp_path / "release-input.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_script_freezes_explicit_release_input_without_provider_calls(
    tmp_path: Path,
    release_input_file: Path,
) -> None:
    destination = tmp_path / "release"

    result = main(
        [
            "--input",
            str(release_input_file),
            "--release-root",
            str(destination),
        ]
    )

    assert result == 0
    assert (destination / "manifest.json").is_file()
    assert set(
        json.loads((destination / "manifest.json").read_text())["domain_statuses"]
    ) == set(DOMAINS)


def test_selection_freeze_cli_is_provider_free(
    monkeypatch,
    tmp_path: Path,
    release_input_file: Path,
) -> None:
    destination = tmp_path / "release"

    def provider_forbidden(*args, **kwargs):
        raise AssertionError("selection freeze must not construct a provider")

    monkeypatch.setattr(cli, "DeepSeekClient", provider_forbidden)
    result = runner.invoke(
        cli.app,
        [
            "selection",
            "freeze",
            "--input",
            str(release_input_file),
            "--release-root",
            str(destination),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "provider_calls=0" in result.stdout
    assert len(result.stdout.split("release_id=")[1].split()[0]) == 64


def test_export_schemas_includes_selection_release_contracts(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app, ["export-schemas", "--output-dir", str(tmp_path)]
    )

    assert result.exit_code == 0
    expected = {
        "stable-split-candidate.schema.json",
        "confirmation-split.schema.json",
        "selection-release-manifest.schema.json",
    }
    assert expected <= {path.name for path in tmp_path.iterdir()}
    exported = {
        "stable-split-candidate.schema.json": StableSplitCandidate.model_json_schema(),
        "confirmation-split.schema.json": ConfirmationSplit.model_json_schema(),
        "selection-release-manifest.schema.json": (
            SelectionReleaseManifest.model_json_schema()
        ),
    }
    for name, schema in exported.items():
        assert json.loads((tmp_path / name).read_text()) == schema
