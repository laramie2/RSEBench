from __future__ import annotations

from pathlib import Path

import pytest

from rsebench.validation import (
    ValidationCatalogs,
    expand_validation_cells,
    load_and_expand,
    load_validation_matrix,
)


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "configs/validation/validation-v1.yaml"


def test_validation_v1_expands_exactly_four_by_four() -> None:
    cells = load_and_expand(MATRIX)

    assert len(cells) == 16
    assert len({cell.cell_id for cell in cells}) == 16
    assert {cell.stage for cell in cells} == {"N1", "N2", "N3", "N4"}
    assert {cell.domain for cell in cells} == {
        "spreadsheet",
        "document",
        "interactive",
        "skill",
    }
    assert all(cell.arm == "noisy" for cell in cells)


def test_each_cell_reuses_domain_clean_evidence() -> None:
    cells = load_and_expand(MATRIX)

    for domain in {cell.domain for cell in cells}:
        domain_cells = tuple(cell for cell in cells if cell.domain == domain)
        assert len({cell.clean_evidence_hash for cell in domain_cells}) == 1
        assert len({cell.method_release_hash for cell in domain_cells}) == 1
        assert len({cell.dataset_release_hash for cell in domain_cells}) == 1


def test_matrix_binds_active_method_to_supported_dataset() -> None:
    matrix = load_validation_matrix(MATRIX)
    catalogs = ValidationCatalogs.load(ROOT)
    incompatible = matrix.model_copy(
        update={
            "methods": {
                **matrix.methods,
                "spreadsheet": "skilladaptor-webshop-validation-v1",
            }
        }
    )

    with pytest.raises(ValueError, match="does not support dataset"):
        expand_validation_cells(incompatible, catalogs)


def test_runtime_and_seed_are_part_of_cell_identity() -> None:
    matrix = load_validation_matrix(MATRIX)
    catalogs = ValidationCatalogs.load(ROOT)
    original = expand_validation_cells(matrix, catalogs)
    changed_matrix = matrix.model_copy(update={"noise_seed": matrix.noise_seed + 1})
    changed = expand_validation_cells(changed_matrix, catalogs)

    assert {cell.identity_hash for cell in original}.isdisjoint(
        {cell.identity_hash for cell in changed}
    )
