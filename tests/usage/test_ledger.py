import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rsebench.usage import (
    TokenUsageEvent,
    aggregate_token_usage,
    record_token_event,
    token_context_environment,
    write_token_usage_artifacts,
)


def _event(**updates) -> TokenUsageEvent:
    payload = {
        "event_id": "a" * 64,
        "timestamp": "2026-08-13T00:00:00+00:00",
        "run_id": "run-1",
        "domain": "math",
        "benchmark": "dapo_fixed_1000",
        "arm": "clean",
        "stage": "rollout",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "cache_hit": False,
        "billed": True,
        "usage_observed": True,
        "status": "success",
        "source": "test",
    }
    payload.update(updates)
    return TokenUsageEvent.model_validate(payload)


def test_event_rejects_inconsistent_or_impossible_usage():
    with pytest.raises(ValidationError, match="prompt plus completion"):
        _event(total_tokens=16)
    with pytest.raises(ValidationError):
        _event(prompt_tokens=-1, total_tokens=4)
    with pytest.raises(ValidationError, match="cache hits cannot be billed"):
        _event(cache_hit=True)
    with pytest.raises(ValidationError, match="cannot claim observed usage"):
        _event(status="error")


def test_context_environment_returns_an_isolated_complete_mapping(tmp_path: Path):
    original = {"KEEP": "yes"}

    result = token_context_environment(
        original,
        ledger_dir=tmp_path / "token_usage",
        run_id="run-1",
        domain="document",
        benchmark="officeqa_full",
        arm="noisy",
        stage="eval",
    )

    assert original == {"KEEP": "yes"}
    assert result == {
        "KEEP": "yes",
        "RSEBENCH_TOKEN_LEDGER_DIR": str(tmp_path / "token_usage"),
        "RSEBENCH_TOKEN_RUN_ID": "run-1",
        "RSEBENCH_TOKEN_DOMAIN": "document",
        "RSEBENCH_TOKEN_BENCHMARK": "officeqa_full",
        "RSEBENCH_TOKEN_ARM": "noisy",
        "RSEBENCH_TOKEN_STAGE": "eval",
    }


def test_writer_and_aggregator_separate_billed_and_logical_tokens(tmp_path: Path):
    ledger = tmp_path / "token_usage"
    context = {
        "run_id": "run-1",
        "domain": "math",
        "benchmark": "dapo_fixed_1000",
        "arm": "clean",
        "stage": "rollout",
    }
    record_token_event(
        ledger_dir=ledger,
        context=context,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        cache_hit=False,
        billed=True,
        status="success",
        source="test",
        provider="deepseek",
        model="deepseek-v4-flash",
        request_key="first",
    )
    record_token_event(
        ledger_dir=ledger,
        context=context,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        cache_hit=True,
        billed=False,
        status="success",
        source="test",
        provider="deepseek",
        model="deepseek-v4-flash",
        request_key="first",
    )
    record_token_event(
        ledger_dir=ledger,
        context={**context, "stage": "critic"},
        usage=None,
        cache_hit=False,
        billed=True,
        status="error",
        source="test",
        provider="deepseek",
        model="deepseek-v4-flash",
        error_type="TimeoutError",
    )

    shards = list((ledger / "events").glob("*.jsonl"))
    assert len(shards) == 1
    assert len(shards[0].read_text(encoding="utf-8").splitlines()) == 3
    summary = aggregate_token_usage(ledger)

    assert summary["attempted_calls"] == 3
    assert summary["successful_calls"] == 2
    assert summary["failed_calls"] == 1
    assert summary["observed_calls"] == 2
    assert summary["unobservable_calls"] == 1
    assert summary["cache_hit_calls"] == 1
    assert summary["observed_coverage"] == pytest.approx(2 / 3)
    assert summary["billed_tokens"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    assert summary["logical_tokens"] == {
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
    }
    assert summary["groups"]["stage"]["rollout"]["attempted_calls"] == 2
    assert summary["groups"]["stage"]["critic"]["unobservable_calls"] == 1


def test_aggregator_deduplicates_identical_events_and_rejects_conflicts(
    tmp_path: Path,
):
    ledger = tmp_path / "token_usage"
    events = ledger / "events"
    events.mkdir(parents=True)
    event = _event()
    encoded = event.model_dump_json()
    (events / "1.jsonl").write_text(encoded + "\n", encoding="utf-8")
    (events / "2.jsonl").write_text(encoded + "\n", encoding="utf-8")

    assert aggregate_token_usage(ledger)["attempted_calls"] == 1

    conflict = event.model_copy(
        update={"prompt_tokens": 11, "completion_tokens": 4}
    )
    (events / "2.jsonl").write_text(
        conflict.model_dump_json() + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="conflicting duplicate event_id"):
        aggregate_token_usage(ledger)


def test_aggregator_rejects_malformed_jsonl(tmp_path: Path):
    events = tmp_path / "token_usage" / "events"
    events.mkdir(parents=True)
    (events / "bad.jsonl").write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed token ledger event"):
        aggregate_token_usage(tmp_path / "token_usage")


def test_artifact_writer_is_idempotent_and_writes_readable_report(tmp_path: Path):
    ledger = tmp_path / "token_usage"
    record_token_event(
        ledger_dir=ledger,
        context={
            "run_id": "run-1",
            "domain": "spreadsheet",
            "benchmark": "spreadsheetbench_verified",
            "arm": "generation",
            "stage": "noise_generator",
        },
        usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        cache_hit=False,
        billed=True,
        status="success",
        source="test",
        provider="deepseek",
        model="deepseek-v4-flash",
    )

    first = write_token_usage_artifacts(ledger)
    second = write_token_usage_artifacts(ledger)

    assert first == second
    assert json.loads((ledger / "summary.json").read_text(encoding="utf-8")) == first
    report = (ledger / "report.md").read_text(encoding="utf-8")
    assert "Billed tokens" in report
    assert "Logical tokens" in report
    assert "10" in report


def test_recording_is_a_noop_without_a_configured_ledger(monkeypatch):
    monkeypatch.delenv("RSEBENCH_TOKEN_LEDGER_DIR", raising=False)

    assert (
        record_token_event(
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            cache_hit=False,
            billed=True,
            status="success",
            source="test",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        is None
    )
