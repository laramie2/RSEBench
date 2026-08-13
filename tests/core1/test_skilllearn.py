from __future__ import annotations

from pathlib import Path

import pytest

from rsebench.core1.skilllearn import (
    build_skilllearn_n1_pair,
    build_skilllearn_n2_pair,
    build_skilllearn_split,
    discover_skilllearn_families,
)


CHECKOUT = Path(
    "/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilllearnbench"
)


def test_discovers_official_20_families_and_100_instances() -> None:
    families = discover_skilllearn_families(CHECKOUT)

    assert len(families) == 20
    assert sum(len(family.instances) for family in families) == 100
    split = build_skilllearn_split(CHECKOUT, families)
    assert len(split.acquisition) == 20
    assert len(split.clean_test) == 80
    assert all(path.name.endswith("-1") for path in split.acquisition)
    assert not any(path.name.endswith("-1") for path in split.clean_test)


def make_instance(tmp_path: Path, family: str, filename: str) -> Path:
    instance = tmp_path / family / f"{family}-1"
    environment = instance / "environment"
    environment.mkdir(parents=True)
    (instance / "instruction.md").write_text(
        f"Complete the {family} task using {filename}.", encoding="utf-8"
    )
    (instance / "task.toml").write_text('[task]\nid="fixture"\n', encoding="utf-8")
    (environment / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (environment / filename).write_bytes(b"fixture-resource")
    (instance / "tests").mkdir()
    (instance / "tests" / "hidden.txt").write_text("secret", encoding="utf-8")
    (instance / "solution").mkdir()
    (instance / "solution" / "solve.py").write_text("pass", encoding="utf-8")
    return instance


@pytest.mark.parametrize(
    ("family", "filename", "expected_kind"),
    [
        ("court-form-filling", "blank.pdf", "form_field_map"),
        ("weighted-gdp-calculation", "gdp.xlsx", "prior_period_workbook"),
        ("dependency-vulnerability-check", "package-lock.json", "deprecated_config"),
        ("video-object-counting", "clip.mp4", "prior_media_manifest"),
        ("organize-messy-files", "paper.docx", "backup_file"),
    ],
)
def test_n2_resource_dispatcher_preserves_visible_inputs_and_hides_verifier(
    tmp_path: Path,
    family: str,
    filename: str,
    expected_kind: str,
) -> None:
    instance = make_instance(tmp_path / "source", family, filename)
    output = tmp_path / "output" / family

    pair = build_skilllearn_n2_pair(instance, output, seed=5)

    assert pair.resource_kind == expected_kind
    assert pair.competing_resource.exists()
    assert not (output / "tests").exists()
    assert not (output / "solution").exists()
    assert (output / "instruction.md").read_text() == (instance / "instruction.md").read_text()
    assert pair.original_hashes == pair.noisy_original_hashes
    added = [
        path
        for path in (output / "environment").rglob("*")
        if path.is_file()
        and path.relative_to(output / "environment").as_posix()
        not in pair.original_hashes
    ]
    assert added == [pair.competing_resource]


def test_n1_is_family_specific_and_keeps_original_instruction(tmp_path: Path) -> None:
    instance = make_instance(
        tmp_path, "weighted-gdp-calculation", "gdp.xlsx"
    )

    pair = build_skilllearn_n1_pair(instance, seed=5)

    original = (instance / "instruction.md").read_text()
    assert pair.noisy_instruction.startswith(original)
    assert pair.strategy == "fixed_spreadsheet_columns"
    assert "columns" in pair.noisy_instruction.casefold()
