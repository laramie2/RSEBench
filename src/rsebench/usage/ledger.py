"""Append-only per-call token events and deterministic aggregation."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel


EVENT_SCHEMA_VERSION = "rsebench.token-usage.v1"
SUMMARY_SCHEMA_VERSION = "rsebench.token-summary.v1"

_CONTEXT_ENV = {
    "ledger_dir": "RSEBENCH_TOKEN_LEDGER_DIR",
    "run_id": "RSEBENCH_TOKEN_RUN_ID",
    "domain": "RSEBENCH_TOKEN_DOMAIN",
    "benchmark": "RSEBENCH_TOKEN_BENCHMARK",
    "arm": "RSEBENCH_TOKEN_ARM",
    "stage": "RSEBENCH_TOKEN_STAGE",
}
_SEQUENCE = itertools.count(1)
_WRITE_LOCK = threading.Lock()


class TokenUsageEvent(StrictModel):
    """One observable top-level model-client operation."""

    schema_version: Literal[EVENT_SCHEMA_VERSION] = EVENT_SCHEMA_VERSION
    event_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    timestamp: datetime
    run_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    arm: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cache_hit: bool
    billed: bool
    usage_observed: bool
    status: Literal["success", "error", "interrupted"]
    source: str = Field(min_length=1)
    request_key: str | None = None
    error_type: str | None = None

    @model_validator(mode="after")
    def validate_accounting(self) -> "TokenUsageEvent":
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        if self.usage_observed and self.total_tokens != (
            self.prompt_tokens + self.completion_tokens
        ):
            raise ValueError("observed total_tokens must equal prompt plus completion")
        if self.cache_hit and self.billed:
            raise ValueError("cache hits cannot be billed")
        if self.status != "success" and self.usage_observed:
            raise ValueError("failed/interrupted calls cannot claim observed usage")
        if not self.usage_observed and any(
            (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        ):
            raise ValueError("unobserved usage must have zero token counts")
        return self


def token_context_environment(
    base: Mapping[str, str] | None,
    *,
    ledger_dir: Path | str,
    run_id: str,
    domain: str,
    benchmark: str,
    arm: str,
    stage: str,
) -> dict[str, str]:
    """Return an isolated subprocess environment with ledger context."""

    result = dict(base or {})
    values = {
        "ledger_dir": str(ledger_dir),
        "run_id": run_id,
        "domain": domain,
        "benchmark": benchmark,
        "arm": arm,
        "stage": stage,
    }
    for name, value in values.items():
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError(f"token context {name} cannot be empty")
        result[_CONTEXT_ENV[name]] = cleaned
    return result


@contextmanager
def token_context_scope(
    *,
    ledger_dir: Path | str,
    run_id: str,
    domain: str,
    benchmark: str,
    arm: str,
    stage: str,
) -> Iterator[None]:
    """Temporarily install token context for in-process provider calls."""

    configured = token_context_environment(
        None,
        ledger_dir=ledger_dir,
        run_id=run_id,
        domain=domain,
        benchmark=benchmark,
        arm=arm,
        stage=stage,
    )
    previous = {key: os.environ.get(key) for key in configured}
    os.environ.update(configured)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _context_value(
    name: str,
    explicit: str | None,
    context: Mapping[str, str] | None,
    *,
    default: str = "unknown",
) -> str:
    value = explicit
    if value is None and context is not None:
        value = context.get(name)
    if value is None:
        value = os.environ.get(_CONTEXT_ENV[name])
    return str(value or default).strip() or default


def _usage_values(usage: Mapping[str, Any] | None) -> tuple[bool, int, int, int]:
    payload = dict(usage or {})
    observed = usage is not None and any(
        key in payload for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    )
    if not observed:
        return False, 0, 0, 0
    prompt = int(payload.get("prompt_tokens") or 0)
    completion = int(payload.get("completion_tokens") or 0)
    total = int(payload.get("total_tokens") or (prompt + completion))
    return True, prompt, completion, total


def record_token_event(
    *,
    usage: Mapping[str, Any] | None,
    cache_hit: bool,
    billed: bool,
    status: Literal["success", "error", "interrupted"],
    source: str,
    provider: str,
    model: str,
    ledger_dir: Path | str | None = None,
    context: Mapping[str, str] | None = None,
    run_id: str | None = None,
    domain: str | None = None,
    benchmark: str | None = None,
    arm: str | None = None,
    stage: str | None = None,
    request_key: str | None = None,
    error_type: str | None = None,
) -> Path | None:
    """Append one validated event, or no-op when no ledger is configured."""

    configured_dir = ledger_dir
    if configured_dir is None and context is not None:
        configured_dir = context.get("ledger_dir")
    if configured_dir is None:
        configured_dir = os.environ.get(_CONTEXT_ENV["ledger_dir"])
    if not str(configured_dir or "").strip():
        return None

    observed, prompt, completion, total = _usage_values(usage)
    if status != "success":
        observed, prompt, completion, total = False, 0, 0, 0
    now = datetime.now(timezone.utc)
    with _WRITE_LOCK:
        sequence = next(_SEQUENCE)
        identity = {
            "run_id": _context_value("run_id", run_id, context),
            "domain": _context_value("domain", domain, context),
            "benchmark": _context_value("benchmark", benchmark, context),
            "arm": _context_value("arm", arm, context),
            "stage": _context_value("stage", stage, context),
            "process_id": os.getpid(),
            "sequence": sequence,
            "timestamp": now.isoformat(),
            "request_key": request_key,
            "cache_hit": cache_hit,
            "status": status,
        }
        event_id = hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        event = TokenUsageEvent(
            event_id=event_id,
            timestamp=now,
            run_id=identity["run_id"],
            domain=identity["domain"],
            benchmark=identity["benchmark"],
            arm=identity["arm"],
            stage=identity["stage"],
            provider=provider,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cache_hit=cache_hit,
            billed=billed,
            usage_observed=observed,
            status=status,
            source=source,
            request_key=request_key,
            error_type=error_type,
        )
        events_dir = Path(configured_dir) / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        shard = events_dir / f"{os.getpid()}.jsonl"
        with shard.open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")
            stream.flush()
        return shard


def _empty_totals() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _empty_rollup() -> dict[str, Any]:
    return {
        "attempted_calls": 0,
        "successful_calls": 0,
        "failed_calls": 0,
        "interrupted_calls": 0,
        "observed_calls": 0,
        "unobservable_calls": 0,
        "cache_hit_calls": 0,
        "observed_coverage": 1.0,
        "billed_tokens": _empty_totals(),
        "logical_tokens": _empty_totals(),
    }


def _add_tokens(target: dict[str, int], event: TokenUsageEvent) -> None:
    target["prompt_tokens"] += event.prompt_tokens
    target["completion_tokens"] += event.completion_tokens
    target["total_tokens"] += event.total_tokens


def _add_event(rollup: dict[str, Any], event: TokenUsageEvent) -> None:
    rollup["attempted_calls"] += 1
    if event.status == "success":
        rollup["successful_calls"] += 1
    elif event.status == "error":
        rollup["failed_calls"] += 1
    else:
        rollup["interrupted_calls"] += 1
    if event.usage_observed:
        rollup["observed_calls"] += 1
    else:
        rollup["unobservable_calls"] += 1
    if event.cache_hit:
        rollup["cache_hit_calls"] += 1
    if event.usage_observed and event.billed and not event.cache_hit:
        _add_tokens(rollup["billed_tokens"], event)
    if event.usage_observed and event.status == "success":
        _add_tokens(rollup["logical_tokens"], event)


def _finalize_rollup(rollup: dict[str, Any]) -> None:
    attempted = rollup["attempted_calls"]
    rollup["observed_coverage"] = (
        rollup["observed_calls"] / attempted if attempted else 1.0
    )


def _read_event_paths(paths: Iterator[Path]) -> list[TokenUsageEvent]:
    by_id: dict[str, TokenUsageEvent] = {}
    for path in sorted(paths):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                event = TokenUsageEvent.model_validate_json(line)
            except Exception as exc:
                raise ValueError(
                    f"malformed token ledger event: {path}:{line_number}"
                ) from exc
            previous = by_id.get(event.event_id)
            if previous is None:
                by_id[event.event_id] = event
            elif previous.model_dump(mode="json") != event.model_dump(mode="json"):
                raise ValueError(f"conflicting duplicate event_id: {event.event_id}")
    return [by_id[event_id] for event_id in sorted(by_id)]


def _read_events(ledger_dir: Path) -> list[TokenUsageEvent]:
    return _read_event_paths(iter((ledger_dir / "events").glob("*.jsonl")))


def _aggregate_events(
    events: list[TokenUsageEvent], *, include_run_id: bool = False
) -> dict[str, Any]:
    dimensions = [
        "domain",
        "benchmark",
        "arm",
        "stage",
        "model",
        "status",
        "source",
    ]
    if include_run_id:
        dimensions.insert(0, "run_id")
    summary: dict[str, Any] = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "event_count": len(events),
        **_empty_rollup(),
        "groups": {dimension: {} for dimension in dimensions},
    }
    for event in events:
        _add_event(summary, event)
        for dimension in summary["groups"]:
            value = str(getattr(event, dimension))
            leaf = summary["groups"][dimension].setdefault(value, _empty_rollup())
            _add_event(leaf, event)
    _finalize_rollup(summary)
    for values in summary["groups"].values():
        for leaf in values.values():
            _finalize_rollup(leaf)
    return summary


def aggregate_token_usage(ledger_dir: Path | str) -> dict[str, Any]:
    """Validate, deduplicate, and aggregate every event in a ledger directory."""

    root = Path(ledger_dir)
    return _aggregate_events(_read_events(root))


def aggregate_token_usage_tree(root_dir: Path | str) -> dict[str, Any]:
    """Aggregate every nested token ledger below a run-tree root.

    Event identifiers are deduplicated globally, so copied ledgers and resumed
    runs cannot silently inflate the reported total.
    """

    root = Path(root_dir)
    paths = (
        path
        for path in root.rglob("*.jsonl")
        if path.parent.name == "events" and path.parent.parent.name == "token_usage"
    )
    return _aggregate_events(_read_event_paths(paths), include_run_id=True)


def _render_report(summary: Mapping[str, Any]) -> str:
    billed = summary["billed_tokens"]
    logical = summary["logical_tokens"]
    return "\n".join(
        [
            "# Token Usage",
            "",
            f"Attempted calls: {summary['attempted_calls']}",
            f"Observed calls: {summary['observed_calls']}",
            f"Unobservable calls: {summary['unobservable_calls']}",
            f"Observed coverage: {summary['observed_coverage']:.4f}",
            f"Cache-hit calls: {summary['cache_hit_calls']}",
            "",
            "| View | Prompt | Completion | Total |",
            "|---|---:|---:|---:|",
            f"| Billed tokens | {billed['prompt_tokens']} | "
            f"{billed['completion_tokens']} | {billed['total_tokens']} |",
            f"| Logical tokens | {logical['prompt_tokens']} | "
            f"{logical['completion_tokens']} | {logical['total_tokens']} |",
            "",
        ]
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_token_usage_artifacts(ledger_dir: Path | str) -> dict[str, Any]:
    """Aggregate a ledger and atomically persist JSON and Markdown summaries."""

    root = Path(ledger_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary = aggregate_token_usage(root)
    _atomic_write(
        root / "summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _atomic_write(root / "report.md", _render_report(summary))
    return summary
