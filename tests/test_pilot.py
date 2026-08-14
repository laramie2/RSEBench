from pathlib import Path

from rsebench.calibration import OperatorMetrics, evaluate_operator_gates
from rsebench.pilot import SplitCounts, build_split_manifest, create_run_directory


def test_pilot_ids_are_subset_of_evolution_and_groups_do_not_leak():
    items = [(f"id-{index}", f"group-{index}") for index in range(10)]
    manifest = build_split_manifest(
        benchmark="fixture",
        items=items,
        counts=SplitCounts(
            total=10,
            evolution=5,
            pilot_evolve=2,
            pilot_eval=1,
            validation=2,
            test=3,
        ),
        seed=42,
    )
    assert set(manifest.pilot_evolve) <= set(manifest.evolution)
    assert set(manifest.pilot_eval) <= set(manifest.evolution)
    assert not set(manifest.pilot_eval) & set(manifest.test)
    assert not set(manifest.evolution) & set(manifest.test)


def test_top_level_split_reserves_groups_for_nested_pilot_counts():
    group_sizes = {
        "g0": 28,
        "g1": 19,
        "g2": 2,
        "g3": 12,
        "g4": 1,
        "g5": 8,
        "g6": 30,
    }
    items = [
        (f"{group}-{index}", group)
        for group, size in group_sizes.items()
        for index in range(size)
    ]

    manifest = build_split_manifest(
        benchmark="nested-groups",
        items=items,
        counts=SplitCounts(
            total=100,
            evolution=50,
            pilot_evolve=12,
            pilot_eval=8,
            validation=20,
            test=30,
        ),
        seed=20260812,
    )

    assert len(manifest.evolution) == 50
    assert len(manifest.pilot_evolve) == 12
    assert len(manifest.pilot_eval) == 8
    assert len(manifest.validation) == 20
    assert len(manifest.test) == 30


def test_operator_rejected_when_label_invariance_is_not_perfect():
    metrics = OperatorMetrics(
        structural_rate=1.0,
        label_invariance_rate=0.99,
        applicability_rate=1.0,
        leakage_rate=0.0,
        clean_score=0.8,
        noisy_l1_score=0.76,
        noisy_l2_score=0.68,
        noisy_l3_score=0.60,
    )
    decision = evaluate_operator_gates(metrics)
    assert not decision.accepted
    assert "label_invariance" in decision.failed_gates


def test_operator_requires_effect_without_collapsing_to_floor():
    metrics = OperatorMetrics(
        structural_rate=1.0,
        label_invariance_rate=1.0,
        applicability_rate=1.0,
        leakage_rate=0.0,
        clean_score=0.8,
        noisy_l1_score=0.77,
        noisy_l2_score=0.70,
        noisy_l3_score=0.62,
    )
    assert evaluate_operator_gates(metrics).accepted


def test_run_directories_are_immutable(tmp_path: Path):
    first = create_run_directory(tmp_path, "pilot-a", "fixed-id")
    assert first.is_dir()
    try:
        create_run_directory(tmp_path, "pilot-a", "fixed-id")
    except FileExistsError:
        pass
    else:
        raise AssertionError("an existing run directory was silently reused")
