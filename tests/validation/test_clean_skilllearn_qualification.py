import json
from pathlib import Path

from rsebench.core1.dataset import resolve_clean_split_paths
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from scripts.build_clean_skilllearn_qualification import (
    FAMILIES,
    build_clean_skilllearn_qualification,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_ROOT = (
    PROJECT_ROOT.parents[1] if ".worktrees" in PROJECT_ROOT.parts else PROJECT_ROOT
)
METHODS_ROOT = SHARED_ROOT / "methods/external"
EXPECTED_FAMILIES = (
    "organize-messy-files",
    "offer-letter-generator",
    "schedule-planning",
    "dependency-vulnerability-check",
    "github-repo-analytics",
    "financial-analysis",
    "stock-data-visualization",
    "enterprise-information-search",
)


def test_clean_skilllearn_family_order_sizes_and_portability(tmp_path: Path) -> None:
    assert FAMILIES == EXPECTED_FAMILIES
    outputs = build_clean_skilllearn_qualification(output_root=tmp_path)

    assert tuple(outputs) == EXPECTED_FAMILIES
    for family, path in outputs.items():
        split = CleanEvolutionSplitManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        assert len(split.train) == 2
        assert len(split.validation) == 1
        assert len(split.clean_test) in {2, 3}
        tasks = split.train + split.validation + split.clean_test
        assert {task.metadata["task_family"] for task in tasks} == {family}
        assert [task.task_id for task in split.train] == [
            f"{family}-1",
            f"{family}-2",
        ]
        assert split.validation[0].task_id == f"{family}-3"
        raw = path.read_text(encoding="utf-8")
        assert "/home/" not in raw
        assert '"noisy"' not in raw
        assert all(
            str(task.artifact_path).startswith("rsebench-methods://")
            for task in tasks
        )
        assert all(
            str(task.metadata["official_instance_path"]).startswith(
                "rsebench-methods://"
            )
            for task in tasks
        )
        resolved = resolve_clean_split_paths(
            split,
            project_root=PROJECT_ROOT,
            data_root=SHARED_ROOT / "data",
            methods_root=METHODS_ROOT,
        )
        for task in resolved.train + resolved.validation + resolved.clean_test:
            assert Path(task.artifact_path or "").is_dir()
            assert Path(task.metadata["official_instance_path"]).is_dir()


def test_clean_skilllearn_builder_is_byte_stable(tmp_path: Path) -> None:
    first = build_clean_skilllearn_qualification(output_root=tmp_path)
    first_bytes = {family: path.read_bytes() for family, path in first.items()}
    index_bytes = (tmp_path / "skilllearn_manifest.json").read_bytes()

    second = build_clean_skilllearn_qualification(output_root=tmp_path)

    assert first == second
    assert {family: path.read_bytes() for family, path in second.items()} == first_bytes
    assert (tmp_path / "skilllearn_manifest.json").read_bytes() == index_bytes
    index = json.loads(index_bytes)
    assert index["families"] == list(EXPECTED_FAMILIES)
    assert index["method_seeds"] == [20260813, 20260814, 20260815]
    assert len(index["seed_skill_hash"]) == 64
