import json
from pathlib import Path

import pytest

from scripts.build_clean_webshop_qualification import (
    build_clean_webshop_split,
    build_clean_webshop_split_v2,
)
from scripts.calibrate_clean_webshop_validation import select_validation_ids


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = (
    PROJECT_ROOT
    / "benchmark/validation/clean_qualification_v1/webshop_source.json"
)
SELECTION_PATH = (
    PROJECT_ROOT
    / "benchmark/validation/clean_qualification_v1/webshop_validation_selection.json"
)


def test_validation_selection_uses_only_repaired_seed_scores() -> None:
    candidate_ids = [735, 994, 1036, 1195, 893, 788, 1180]
    seed_scores = {
        735: 0.0,
        994: 0.0,
        1036: 0.0,
        1195: 1.0,
        893: 0.0,
        788: 1.0,
        1180: 0.0,
    }

    selected = select_validation_ids(candidate_ids, seed_scores)

    assert selected == [1195, 788, 735, 994, 1036]


@pytest.mark.parametrize(
    "seed_scores",
    [
        {735: 0.0, 994: 0.0, 1036: 0.0, 1195: 1.0},
        {735: 0.1, 994: 0.2, 1036: 1.0, 1195: 1.0},
    ],
)
def test_validation_selection_requires_two_successes_and_three_failures(
    seed_scores: dict[int, float],
) -> None:
    with pytest.raises(ValueError, match="two successes and three failures"):
        select_validation_ids(list(seed_scores), seed_scores)


def test_validation_selection_rejects_execution_failures() -> None:
    with pytest.raises(RuntimeError, match="execution failures"):
        select_validation_ids(
            [735, 994, 1036, 1195, 788],
            {735: 0.0, 994: 0.0, 1036: 0.0, 1195: 1.0, 788: 1.0},
            execution_failures={"goal_994": "RuntimeError: invalid action"},
        )


def test_clean_webshop_manifest_is_disjoint_noise_free_and_budget_locked() -> None:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    assert len(source["train"]) == 5
    assert len(source["validation_candidates"]) == 24
    assert len(source["test"]) == 20
    assert "N1" not in source and "N2" not in source
    assert source["selection_policy"]["uses_model_outcomes"] is False
    split = build_clean_webshop_split(
        source_path=SOURCE_PATH,
        selection_path=SELECTION_PATH,
    )

    assert (len(split.train), len(split.validation), len(split.clean_test)) == (
        5,
        5,
        20,
    )
    all_tasks = split.train + split.validation + split.clean_test
    assert len({task.task_id for task in all_tasks}) == 30
    assert '"noisy"' not in split.model_dump_json()
    assert split.metadata["runtime"] == {
        "max_iterations": 3,
        "max_episode_steps": 15,
        "min_sample_size": 5,
    }
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    assert [task.task_id for task in split.validation] == [
        f"goal_{goal_idx}" for goal_idx in selection["selected_ids"]
    ]
    assert selection["uses_evolved_outcomes"] is False
    assert selection["uses_clean_test_outcomes"] is False


def test_webshop_v2_preserves_split_and_pins_runtime_repairs() -> None:
    v1 = build_clean_webshop_split(
        source_path=SOURCE_PATH,
        selection_path=SELECTION_PATH,
    )
    v2 = build_clean_webshop_split_v2(
        source_path=SOURCE_PATH,
        selection_path=SELECTION_PATH,
    )

    for partition in ("train", "validation", "clean_test"):
        assert [task.task_id for task in getattr(v2, partition)] == [
            task.task_id for task in getattr(v1, partition)
        ]
    assert v2.metadata["qualification_version"] == "clean-qualification-v2"
    assert v2.metadata["validation_selection"] == v1.metadata["validation_selection"]
    assert v2.metadata["runtime_baseline"]["patch_hashes"][
        "skilladaptor-clean-qualification.patch"
    ] != v1.metadata["validation_selection"]["baseline"]["patch_hashes"][
        "skilladaptor-clean-qualification.patch"
    ]
    assert v2.metadata["qualification_amendment"]["repairs"] == [
        "normalize_numeric_webshop_task_ids",
        "fallback_to_available_navigation_after_bad_action_repair",
        "skip_one_malformed_linker_attribution_candidate",
    ]
    assert v2.metadata["calibration_selection_path"].startswith(
        "rsebench-project://"
    )
