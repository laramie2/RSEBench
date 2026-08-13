from pathlib import Path
import subprocess
import sys

from rsebench.core1.dataset import resolve_split_paths
from rsebench.evolution.contracts import EvolutionSplitManifest
from scripts.build_expanded_n1_validation import (
    EXPANDED_ROOT,
    PROJECT_ROOT,
    build_expanded_n1_validation,
)


EXPECTED_SIZES = {
    "spreadsheetbench_verified": (8, 4, 20),
    "officeqa_full": (8, 4, 20),
    "webshop": (5, 3, 10),
}


def test_expanded_builder_direct_cli_entrypoint_is_importable():
    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts/build_expanded_n1_validation.py"), "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def _load(path: Path) -> EvolutionSplitManifest:
    return EvolutionSplitManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _assert_disjoint(split: EvolutionSplitManifest) -> None:
    train = {pair.task_id for pair in split.train}
    validation = {pair.task_id for pair in split.validation}
    test = {task.task_id for task in split.clean_test}
    assert train.isdisjoint(validation)
    assert train.isdisjoint(test)
    assert validation.isdisjoint(test)


def test_expanded_task_domain_manifests_have_frozen_sizes(tmp_path: Path):
    outputs = build_expanded_n1_validation(output_root=tmp_path)

    for benchmark, sizes in EXPECTED_SIZES.items():
        path = outputs[benchmark]
        split = _load(path)
        assert (len(split.train), len(split.validation), len(split.clean_test)) == sizes
        _assert_disjoint(split)


def test_skilllearn_candidates_are_independent_2_1_2_family_units(tmp_path: Path):
    outputs = build_expanded_n1_validation(output_root=tmp_path)
    skilllearn = {
        key: path for key, path in outputs.items() if key.startswith("skilllearnbench/")
    }

    assert len(skilllearn) >= 4
    for key, path in skilllearn.items():
        split = _load(path)
        assert (len(split.train), len(split.validation), len(split.clean_test)) == (2, 1, 2)
        families = {
            task.metadata["task_family"]
            for pair in [*split.train, *split.validation]
            for task in (pair.clean, pair.noisy)
        }
        families.update(task.metadata["task_family"] for task in split.clean_test)
        assert families == {key.split("/", 1)[1]}
        _assert_disjoint(split)


def test_expanded_manifests_are_portable_and_resolvable():
    outputs = build_expanded_n1_validation(output_root=EXPANDED_ROOT)

    for path in outputs.values():
        raw = path.read_text(encoding="utf-8")
        assert "/home/" not in raw
        split = _load(path)
        resolved = resolve_split_paths(
            split,
            project_root=PROJECT_ROOT,
            data_root=PROJECT_ROOT.parents[1] / "data",
            methods_root=PROJECT_ROOT.parents[1] / "methods/external",
        )
        for pair in [*resolved.train, *resolved.validation]:
            for task in (pair.clean, pair.noisy):
                if task.artifact_path:
                    assert Path(task.artifact_path).exists()
        for task in resolved.clean_test:
            if task.artifact_path:
                assert Path(task.artifact_path).exists()
