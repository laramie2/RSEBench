from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAMILIES = (
    "organize-messy-files",
    "offer-letter-generator",
    "schedule-planning",
    "dependency-vulnerability-check",
)


def _load_script():
    path = PROJECT_ROOT / "scripts/aggregate_noise_screen_selection.py"
    assert path.is_file(), "noise-screen selection aggregator is missing"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _span(level: str, name: str, *, task_id: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "level": level,
        "name": name,
        "task_id": task_id,
        "started_at": now,
        "ended_at": now,
        "duration_seconds": 0.1,
        "status": "completed",
        "error_type": None,
        "metadata": {},
    }


def _replay(*, coverage: float = 1.0, include_timing: bool = True) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    artifact_hashes = {"seed": "a" * 64, "clean": "b" * 64}
    payload = {
        "schema_version": "rsebench.fixed-artifact-replay.v1",
        "output_dir": "/tmp/replay",
        "benchmark": "fixture",
        "domain": "document",
        "repeat_count": 3,
        "order_policy": "cyclic_rotation",
        "artifact_order": ["seed", "clean"],
        "reference_label": "seed",
        "task_ids": ["t1", "t2"],
        "task_manifest_hash": "c" * 64,
        "artifact_paths": {"seed": "/tmp/seed", "clean": "/tmp/clean"},
        "artifact_hashes": artifact_hashes,
        "observations": [
            {
                "repeat": repeat,
                "artifact_label": label,
                "artifact_hash": artifact_hashes[label],
                "stage": f"replay_{label}_r{repeat}",
                "started_at": now,
                "ended_at": now,
                "duration_seconds": 0.1,
                "evaluation": {
                    "score": 1.0,
                    "per_task_scores": {"t1": 1.0, "t2": 1.0},
                    "diagnostics": {},
                },
            }
            for repeat in (1, 2, 3)
            for label in ("seed", "clean")
        ],
        "summaries": {
            label: {
                "scores": [1.0, 1.0, 1.0],
                "mean_score": 1.0,
                "score_sample_stddev": 0.0,
                "min_score": 1.0,
                "max_score": 1.0,
                "deltas_vs_reference": [0.0, 0.0, 0.0],
                "mean_delta_vs_reference": 0.0,
                "delta_sample_stddev": 0.0,
            }
            for label in ("seed", "clean")
        },
        "started_at": now,
        "ended_at": now,
        "duration_seconds": 1.0,
        "resume_history": [],
        "token_usage": {
            "observed_coverage": coverage,
            "billed_tokens": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        },
    }
    if include_timing:
        payload["timing"] = {
            "run": _span("run", "fixed_artifact_replay"),
            "stages": [
                _span("stage", f"replay_{label}_r{repeat}")
                for repeat in (1, 2, 3)
                for label in ("seed", "clean")
            ],
            "tasks": [
                _span(
                    "task",
                    f"replay_{label}_r{repeat}",
                    task_id=task_id,
                )
                for repeat in (1, 2, 3)
                for label in ("seed", "clean")
                for task_id in ("t1", "t2")
            ],
        }
    return payload


def _seed(method_seed: int, delta: float = 0.05) -> dict:
    return {
        "method_seed": method_seed,
        "accepted_update_count": 1,
        "artifact_changed": True,
        "mean_delta_vs_seed": delta,
        "execution_complete": True,
        "replay_count": 3,
    }


def _identity(seed: int) -> dict:
    return {
        "baseline_fingerprint": "1" * 64,
        "evolution_input_hash": "2" * 64,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "provider_config_hash": "3" * 64,
        "method_seed": seed,
        "artifact_hash": "b" * 64,
    }


def _pool(candidate_index: int = 2) -> dict:
    seeds = (20260813, 20260814, 20260815)
    return {
        "candidate_index": candidate_index,
        "seeds": [_seed(seed) for seed in seeds],
        "execution_coverage": 1.0,
        "noise_applicability": 1.0,
        "expected_task_ids": ["train-1", "validation-1"],
        "executed_task_ids": ["train-1", "validation-1"],
        "candidate_audit": {
            "static_gates": {
                "noise_applicability": {
                    "N1": {"status": "pass", "coverage": 1.0},
                    "N2": {"status": "pass", "coverage": 1.0},
                    "N3": {"status": "pending", "coverage": None},
                    "N4": {"status": "pending", "coverage": None},
                }
            }
        },
        "trace_audit": {
            "N3": {"status": "pass", "coverage": 1.0},
            "N4": {"status": "pass", "coverage": 1.0},
        },
        "domain_audit": {"passed": True, "failure_reasons": []},
        "replays": [_replay() for _ in seeds],
        "reuse_checks": [
            {"actual": _identity(seed), "expected": _identity(seed)} for seed in seeds
        ],
    }


def _family_row(*, ready: bool) -> dict:
    return {
        "seeds": [
            {
                "method_seed": seed,
                "accepted_update_count": 1 if ready or index == 0 else 0,
                "artifact_changed": ready or index == 0,
                "validation_complete": True,
                "reuse_check": {
                    "actual": _identity(seed),
                    "expected": _identity(seed),
                },
            }
            for index, seed in enumerate((20260813, 20260814, 20260815))
        ]
    }


def _skilllearn(*, ready_count: int = 4) -> dict:
    return {
        "families": {
            family: _family_row(ready=index < ready_count)
            for index, family in enumerate(FAMILIES)
        },
        "expected_task_ids": [f"task-{index}" for index in range(12)],
        "executed_task_ids": [f"task-{index}" for index in range(12)],
        "candidate_audit": {
            "static_gates": {
                "noise_applicability": {
                    "N1": {"status": "pass", "coverage": 1.0},
                    "N2": {"status": "pass", "coverage": 1.0},
                    "N3": {"status": "pending", "coverage": None},
                    "N4": {"status": "pending", "coverage": None},
                }
            }
        },
        "trace_audit": {
            "N3": {"status": "pass", "coverage": 1.0},
            "N4": {"status": "pass", "coverage": 1.0},
        },
        "domain_audit": {"passed": True, "failure_reasons": []},
    }


def test_three_ready_skilllearn_families_freeze_without_candidate_substitution() -> (
    None
):
    module = _load_script()
    payload = {
        "domains": {
            "spreadsheetbench_verified": _pool(),
            "officeqa_full": _pool(),
            "webshop": _pool(),
        },
        "skilllearn": _skilllearn(ready_count=3),
    }

    status = module.build_selection_status(payload)

    assert status.domains["skilllearnbench"].next_action == "freeze_candidate"
    assert status.domains["skilllearnbench"].selected_candidate_index == 1


def test_two_ready_skilllearn_families_block_fixed_families() -> None:
    module = _load_script()
    payload = {
        "domains": {
            "spreadsheetbench_verified": _pool(),
            "officeqa_full": _pool(),
            "webshop": _pool(),
        },
        "skilllearn": _skilllearn(ready_count=2),
    }

    status = module.build_selection_status(payload)

    row = status.domains["skilllearnbench"]
    assert row.next_action == "clean_blocked_skilllearn_families"
    assert "run_candidate_3" not in row.model_dump_json()


def test_missing_timing_or_incomplete_token_coverage_blocks_aggregation() -> None:
    module = _load_script()
    payload = {
        "domains": {
            "spreadsheetbench_verified": _pool(),
            "officeqa_full": _pool(),
            "webshop": _pool(),
        },
        "skilllearn": _skilllearn(),
    }
    payload["domains"]["webshop"]["replays"][0] = _replay(include_timing=False)
    payload["domains"]["webshop"]["replays"][1] = _replay(coverage=0.5)

    status = module.build_selection_status(payload)

    row = status.domains["webshop"]
    assert row.next_action == "rerun_candidate_1"
    assert "missing_replay_timing" in row.reasons
    assert "incomplete_token_observation" in row.reasons


def test_incomplete_replay_observation_denominator_blocks_aggregation() -> None:
    module = _load_script()
    payload = {
        "domains": {
            "spreadsheetbench_verified": _pool(),
            "officeqa_full": _pool(),
            "webshop": _pool(),
        },
        "skilllearn": _skilllearn(),
    }
    payload["domains"]["webshop"]["replays"][0]["observations"].pop()

    status = module.build_selection_status(payload)

    row = status.domains["webshop"]
    assert row.next_action == "rerun_candidate_1"
    assert "incomplete_replay_observation_denominator" in row.reasons


def test_mixed_reuse_fingerprint_requests_fixed_fallback_matrix() -> None:
    module = _load_script()
    payload = {
        "domains": {
            "spreadsheetbench_verified": _pool(),
            "officeqa_full": _pool(),
            "webshop": _pool(),
        },
        "skilllearn": _skilllearn(),
    }
    payload["domains"]["officeqa_full"]["reuse_checks"][0]["actual"][
        "baseline_fingerprint"
    ] = "9" * 64

    status = module.build_selection_status(payload)

    row = status.domains["officeqa_full"]
    assert row.next_action == "rerun_candidate_1"
    assert "reuse_identity_mismatch" in row.reasons


def test_individually_matching_but_mixed_fingerprints_reject_reuse() -> None:
    module = _load_script()
    officeqa = _pool()
    officeqa["reuse_checks"][0]["actual"]["baseline_fingerprint"] = "9" * 64
    officeqa["reuse_checks"][0]["expected"]["baseline_fingerprint"] = "9" * 64
    payload = {
        "domains": {
            "spreadsheetbench_verified": _pool(),
            "officeqa_full": officeqa,
            "webshop": _pool(),
        },
        "skilllearn": _skilllearn(),
    }

    status = module.build_selection_status(payload)

    row = status.domains["officeqa_full"]
    assert row.next_action == "rerun_candidate_1"
    assert "mixed_reuse_fingerprints" in row.reasons


def test_unresolved_trace_applicability_is_a_typed_failure() -> None:
    module = _load_script()
    audit = {
        "static_gates": {
            "noise_applicability": {
                "N1": {"status": "pass", "coverage": 1.0},
                "N2": {"status": "pass", "coverage": 1.0},
                "N3": {"status": "pending", "coverage": None},
                "N4": {"status": "pending", "coverage": None},
            }
        }
    }
    failures = module.merged_audit_failures(
        candidate_audit=audit,
        trace_audit={"N3": {"status": "pending"}, "N4": {"status": "pass"}},
    )
    assert "pending_noise_applicability:N3" in failures
    assert "pending_noise_applicability:N4" not in failures


def test_skilllearn_pending_trace_gate_blocks_even_three_ready_families() -> None:
    module = _load_script()
    skilllearn = _skilllearn(ready_count=3)
    skilllearn["trace_audit"]["N3"] = {"status": "pending", "coverage": None}
    payload = {
        "domains": {
            "spreadsheetbench_verified": _pool(),
            "officeqa_full": _pool(),
            "webshop": _pool(),
        },
        "skilllearn": skilllearn,
    }

    status = module.build_selection_status(payload)

    row = status.domains["skilllearnbench"]
    assert row.next_action == "clean_blocked_skilllearn_families"
    assert "pending_noise_applicability:N3" in row.reasons


def test_sign_inconsistent_replay_requests_five_before_candidate_decision() -> None:
    module = _load_script()
    payload = {
        "domains": {
            "spreadsheetbench_verified": {
                **_pool(),
                "paired_replay_deltas": [0.1, -0.1, 0.2],
                "replay_count": 3,
            },
            "officeqa_full": _pool(),
            "webshop": _pool(),
        },
        "skilllearn": _skilllearn(),
    }

    status = module.build_selection_status(payload)

    assert (
        status.domains["spreadsheetbench_verified"].next_action == "extend_replay_to_5"
    )
