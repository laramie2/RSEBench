import json
from pathlib import Path

from rsebench.usage.backfill import (
    audit_historical_usage,
    scan_deepseek_cache,
    scan_skillopt_training_totals,
    scan_unobservable_evaluations,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _skillopt_summary(path: Path, *, calls: int, prompt: int, completion: int) -> None:
    _write_json(
        path,
        {
            "token_summary": {
                "_total": {
                    "calls": calls,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": prompt + completion,
                },
                "rollout": {
                    "calls": calls,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": prompt + completion,
                },
            }
        },
    )


def test_historical_audit_uses_only_exact_observable_usage(tmp_path: Path) -> None:
    project = tmp_path / "project"
    run = project / "outputs/runs/paired-evolution/old-skillopt"
    _write_json(run / "result.json", {"method": "skillopt"})
    _skillopt_summary(
        run / "clean/native_train/summary.json", calls=1, prompt=10, completion=5
    )
    _skillopt_summary(
        run / "noisy/native_train/summary.json", calls=2, prompt=7, completion=3
    )

    cache = project / "outputs/cache/model"
    _write_json(
        cache / "first.json",
        {
            "model": "deepseek-v4-flash",
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            "content": "one",
        },
    )
    _write_json(
        cache / "second.json",
        {
            "model": "deepseek-v4-flash",
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
            "content": "two",
        },
    )
    (cache / "alias.json").symlink_to(cache / "first.json")

    old_eval = run / "seed/evaluation/native_eval"
    _write_json(old_eval / "eval_summary.json", {"hard": 0.0})
    for task_id in ("a", "b", "c"):
        _write_json(old_eval / f"predictions/{task_id}/conversation.json", [])

    accounted_eval = run / "accounted/evaluation/native_eval"
    _write_json(
        accounted_eval / "eval_summary.json",
        {"token_summary": {"_total": {"calls": 1, "total_tokens": 99}}},
    )
    _write_json(accounted_eval / "predictions/skip/conversation.json", [])

    reused_eval = run / "clean/clean_test_evaluation"
    _write_json(reused_eval / "reused.json", {"reason": "identical_skill_hash"})
    _write_json(reused_eval / "native_eval/eval_summary.json", {"hard": 1.0})
    _write_json(reused_eval / "native_eval/predictions/skip/conversation.json", [])

    skillopt = scan_skillopt_training_totals(project)
    cache_scan = scan_deepseek_cache(project)
    unobservable = scan_unobservable_evaluations(project)
    summary = audit_historical_usage(project, tmp_path / "audit")

    assert skillopt["calls"] == 3
    assert skillopt["tokens"]["total_tokens"] == 25
    assert cache_scan["calls"] == 2
    assert cache_scan["tokens"]["total_tokens"] == 15
    assert cache_scan["context"] == "unknown"
    assert unobservable["calls"] == 3
    assert summary["exact_lower_bound"] is True
    assert summary["observed_calls"] == 5
    assert summary["unobservable_calls"] == 3
    assert summary["billed_tokens"]["total_tokens"] == 40
    assert summary["sources"]["skillopt_training"]["total_tokens"] == 25
    assert summary["sources"]["legacy_deepseek_cache"]["total_tokens"] == 15
    assert summary["source_file_counts"] == {
        "skillopt_training_summaries": 2,
        "deepseek_cache_files": 2,
        "unobservable_evaluation_conversations": 3,
    }
    assert "estimated_tokens" not in json.dumps(summary)
    assert json.loads((tmp_path / "audit/summary.json").read_text()) == summary
    report = (tmp_path / "audit/report.md").read_text(encoding="utf-8")
    assert "exact lower bound" in report.lower()
    assert "estimate" not in report.lower()
