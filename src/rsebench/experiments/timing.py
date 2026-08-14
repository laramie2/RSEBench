"""Append-only hierarchical timing for experiment attempts."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel


class TimingSpan(StrictModel):
    level: Literal["run", "stage", "task"]
    name: str = Field(min_length=1)
    task_id: str | None = None
    started_at: datetime
    ended_at: datetime
    duration_seconds: float = Field(ge=0.0)
    status: Literal["completed", "failed", "interrupted"]
    error_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span(self) -> "TimingSpan":
        if self.started_at.utcoffset() is None or self.ended_at.utcoffset() is None:
            raise ValueError("timing timestamps must be timezone-aware")
        if self.ended_at < self.started_at:
            raise ValueError("timing span ends before it starts")
        if (self.level == "task") != (self.task_id is not None):
            raise ValueError("task_id is required exactly for task-level timing")
        if self.status == "completed" and self.error_type is not None:
            raise ValueError("completed timing span cannot have error_type")
        if self.status != "completed" and not self.error_type:
            raise ValueError("failed or interrupted timing span requires error_type")
        return self


class TimingSummary(StrictModel):
    run: TimingSpan
    stages: list[TimingSpan]
    tasks: list[TimingSpan]

    @model_validator(mode="after")
    def validate_levels(self) -> "TimingSummary":
        if self.run.level != "run":
            raise ValueError("summary run span must have run level")
        if any(span.level != "stage" for span in self.stages):
            raise ValueError("summary stages must contain only stage spans")
        if any(span.level != "task" for span in self.tasks):
            raise ValueError("summary tasks must contain only task spans")
        return self


class TimingRecorder:
    """Record finalized spans immediately and materialize one typed summary."""

    def __init__(
        self,
        output_root: Path | str,
        *,
        utc_now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.output_root = Path(output_root)
        self.timing_root = self.output_root / "timing"
        self.timing_root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.timing_root / "events.jsonl"
        self.summary_path = self.timing_root / "summary.json"
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._spans: list[TimingSpan] = []

    def _append(self, span: TimingSpan) -> None:
        payload = json.dumps(
            span.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._spans.append(span)

    @contextmanager
    def span(
        self,
        *,
        level: Literal["run", "stage", "task"],
        name: str,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        started_at = self._utc_now()
        started_monotonic = self._monotonic()
        status: Literal["completed", "failed", "interrupted"] = "completed"
        error_type: str | None = None
        try:
            yield
        except BaseException as exc:
            status = (
                "interrupted"
                if isinstance(exc, (KeyboardInterrupt, SystemExit))
                else "failed"
            )
            error_type = type(exc).__name__
            raise
        finally:
            ended_monotonic = self._monotonic()
            ended_at = self._utc_now()
            self._append(
                TimingSpan(
                    level=level,
                    name=name,
                    task_id=task_id,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_seconds=max(0.0, ended_monotonic - started_monotonic),
                    status=status,
                    error_type=error_type,
                    metadata=metadata or {},
                )
            )

    def finalize(self) -> TimingSummary:
        runs = [span for span in self._spans if span.level == "run"]
        if len(runs) != 1:
            raise RuntimeError(f"timing summary requires exactly one run span, got {len(runs)}")
        summary = TimingSummary(
            run=runs[0],
            stages=[span for span in self._spans if span.level == "stage"],
            tasks=[span for span in self._spans if span.level == "task"],
        )
        encoded = (
            json.dumps(
                summary.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        temporary = self.summary_path.with_suffix(".json.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, self.summary_path)
        return summary


__all__ = ["TimingRecorder", "TimingSpan", "TimingSummary"]
