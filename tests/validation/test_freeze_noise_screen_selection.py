from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

from rsebench import cli
from rsebench.evidence import canonical_hash
from rsebench.selection.contracts import (
    DomainSelectionStatus,
    SelectionStatus,
)
from rsebench.selection.qualification import (
    DomainScreeningGeneralization,
    ScreeningGeneralizationAggregate,
)
from rsebench.selection import ConfirmationSplit, StableSplitCandidate
from rsebench.selection.contracts import SelectionReleaseManifest
from rsebench.selection.release import (
    QualificationReleaseCompanion,
    ScreeningReleaseCompanion,
    make_screening_release_companion,
)
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
def root_release_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    release_inputs = RELEASE_FIXTURES.make_release_inputs()
    selection_root = tmp_path / "selection"
    run_root = tmp_path / "runs"
    destination = tmp_path / "release"
    selection_root.mkdir()
    run_root.mkdir()

    candidate_index: dict[str, list[str]] = {}
    confirmations: dict[str, str] = {}
    for benchmark in sorted(DOMAINS):
        candidate_relative = f"candidates/{benchmark}/candidate_1.json"
        candidate_path = selection_root / candidate_relative
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text(
            release_inputs["candidates"][benchmark].model_dump_json(indent=2) + "\n"
        )
        candidate_index[benchmark] = [candidate_relative]
        confirmation_relative = f"confirmation/{benchmark}.json"
        confirmation_path = selection_root / confirmation_relative
        confirmation_path.parent.mkdir(parents=True, exist_ok=True)
        confirmation_path.write_text(
            release_inputs["confirmations"][benchmark].model_dump_json(indent=2)
            + "\n"
        )
        confirmations[benchmark] = confirmation_relative
    (selection_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "rsebench.selection-candidate-index.v1",
                "selection_version": "noise-screen-v1",
                "candidates": candidate_index,
                "confirmation": confirmations,
                "confirmation_seal": "confirmation_seal.json",
                "exposure_registry_hash": release_inputs[
                    "exposure_registry"
                ].registry_hash,
            }
        )
    )
    for name, value in (
        ("exposure_registry.json", release_inputs["exposure_registry"]),
        ("confirmation_seal.json", release_inputs["confirmation_seal"]),
        ("resource_lock.json", release_inputs["resource_lock"]),
    ):
        (selection_root / name).write_text(value.model_dump_json(indent=2) + "\n")

    selection_status = SelectionStatus(
        domains={
            benchmark: DomainSelectionStatus(
                benchmark=benchmark,
                selected_candidate_index=1,
                next_action="freeze_candidate",
            )
            for benchmark in DOMAINS
        }
    )
    screening = ScreeningGeneralizationAggregate(
        domains={
            benchmark: DomainScreeningGeneralization(
                status="clean_generalization_ready"
            )
            for benchmark in DOMAINS
        },
        all_ready=True,
    )
    (run_root / "selection_status.json").write_text(
        selection_status.model_dump_json(indent=2) + "\n"
    )
    (run_root / "screening_generalization.json").write_text(
        screening.model_dump_json(indent=2) + "\n"
    )
    unsigned = {
        "schema_version": "rsebench.qualification-release-companion.v1",
        "selection_status_hash": canonical_hash(
            selection_status.model_dump(mode="json")
        ),
        "selected_candidate_indices": {benchmark: 1 for benchmark in DOMAINS},
        "selection_hashes": {
            benchmark: release_inputs["candidates"][benchmark].selection_hash
            for benchmark in DOMAINS
        },
        "decisions": {
            benchmark: release_inputs["decisions"][benchmark].model_dump(mode="json")
            for benchmark in DOMAINS
        },
        "decision_bases": {
            benchmark: (
                "skilllearn_fixed_family_gate_v1"
                if benchmark == "skilllearnbench"
                else "candidate_fixed_replay_v1"
            )
            for benchmark in DOMAINS
        },
        "baseline_fingerprints": release_inputs["baseline_fingerprints"],
        "evidence_hashes": {f"owned:{benchmark}": "8" * 64 for benchmark in DOMAINS},
    }
    companion = QualificationReleaseCompanion(
        **unsigned,
        companion_hash=canonical_hash(unsigned),
    )
    (run_root / "release_qualification.json").write_text(
        companion.model_dump_json(indent=2) + "\n"
    )
    monkeypatch.setattr(
        "rsebench.selection.qualification_io.derive_release_qualification_companion",
        lambda **kwargs: companion,
    )
    screening_companion = make_screening_release_companion(
        selection_status=selection_status,
        selection_hashes={
            benchmark: release_inputs["candidates"][benchmark].selection_hash
            for benchmark in DOMAINS
        },
        aggregate=screening,
        evidence_hashes={
            f"owned:{benchmark}": "7" * 64 for benchmark in DOMAINS
        },
    )
    monkeypatch.setattr(
        "rsebench.selection.qualification_io.derive_release_screening_companion",
        lambda **kwargs: screening_companion,
    )
    monkeypatch.setattr(
        "rsebench.selection.resources.validate_resource_lock_materializations",
        lambda *args, **kwargs: None,
    )
    return selection_root, run_root, destination


def test_task8_root_owned_invocation_is_provider_free(
    root_release_fixture: tuple[Path, Path, Path],
) -> None:
    selection_root, run_root, destination = root_release_fixture

    result = main(
        [
            "--selection-root",
            str(selection_root),
            "--run-root",
            str(run_root),
            "--release-root",
            str(destination),
        ]
    )

    assert result == 0
    assert (destination / "manifest.json").is_file()
    emitted = QualificationReleaseCompanion.model_validate_json(
        (destination / "release_qualification.json").read_text()
    )
    stored = QualificationReleaseCompanion.model_validate_json(
        (run_root / "release_qualification.json").read_text()
    )
    assert emitted == stored
    screening = ScreeningReleaseCompanion.model_validate_json(
        (destination / "screening_release.json").read_text()
    )
    assert screening.aggregate == ScreeningGeneralizationAggregate.model_validate_json(
        (run_root / "screening_generalization.json").read_text()
    )
    assert screening.evidence_hashes


def test_task8_root_owned_cli_reports_zero_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
    root_release_fixture: tuple[Path, Path, Path],
) -> None:
    selection_root, run_root, destination = root_release_fixture

    def provider_forbidden(*args, **kwargs):
        raise AssertionError("root-owned freeze must not construct a provider")

    monkeypatch.setattr(cli, "DeepSeekClient", provider_forbidden)
    result = runner.invoke(
        cli.app,
        [
            "selection",
            "freeze",
            "--selection-root",
            str(selection_root),
            "--run-root",
            str(run_root),
            "--release-root",
            str(destination),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "provider_calls=0" in result.stdout


def test_root_mode_refuses_nonready_screening_even_with_passing_companion(
    root_release_fixture: tuple[Path, Path, Path],
) -> None:
    selection_root, run_root, destination = root_release_fixture
    payload = json.loads((run_root / "screening_generalization.json").read_text())
    payload["all_ready"] = False
    payload["domains"]["webshop"]["status"] = "clean_generalization_failed"
    (run_root / "screening_generalization.json").write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="screening aggregate differs"):
        main(
            [
                "--selection-root",
                str(selection_root),
                "--run-root",
                str(run_root),
                "--release-root",
                str(destination),
            ]
        )


def test_root_mode_refuses_companion_that_differs_from_owned_evidence(
    root_release_fixture: tuple[Path, Path, Path],
) -> None:
    selection_root, run_root, destination = root_release_fixture
    payload = json.loads((run_root / "release_qualification.json").read_text())
    payload["evidence_hashes"]["owned:webshop"] = "9" * 64
    (run_root / "release_qualification.json").write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="qualification companion"):
        main(
            [
                "--selection-root",
                str(selection_root),
                "--run-root",
                str(run_root),
                "--release-root",
                str(destination),
            ]
        )


def test_script_parser_rejects_unowned_input_bypass() -> None:
    from scripts.freeze_noise_screen_selection import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--input", "input.json", "--release-root", "release"])


def test_selection_freeze_cli_rejects_unowned_input_bypass() -> None:
    result = runner.invoke(
        cli.app,
        [
            "selection",
            "freeze",
            "--input",
            "input.json",
            "--release-root",
            "release",
        ],
    )

    assert result.exit_code != 0
    help_result = runner.invoke(cli.app, ["selection", "freeze", "--help"])
    assert help_result.exit_code == 0
    assert "--input" not in help_result.stdout


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
