from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from rsebench.experiments.timing import TimingRecorder, TimingSpan


class SequenceClock:
    def __init__(self, values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


def test_timing_recorder_uses_utc_and_monotonic_duration(tmp_path: Path) -> None:
    utc = SequenceClock(
        [
            datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 14, 10, 0, 2, 500000, tzinfo=timezone.utc),
        ]
    )
    monotonic = SequenceClock([10.0, 12.5])
    recorder = TimingRecorder(tmp_path, utc_now=utc, monotonic=monotonic)

    with recorder.span(level="run", name="clean"):
        pass
    summary = recorder.finalize()

    assert summary.run.duration_seconds == 2.5
    assert summary.run.status == "completed"
    assert summary.run.started_at.utcoffset() is not None
    assert summary.run.ended_at.utcoffset() is not None
    event_lines = (tmp_path / "timing/events.jsonl").read_text().splitlines()
    assert len(event_lines) == 1
    assert json.loads(event_lines[0])["name"] == "clean"
    persisted = json.loads((tmp_path / "timing/summary.json").read_text())
    assert persisted["run"]["duration_seconds"] == 2.5


def test_failed_span_is_persisted_before_exception_propagates(tmp_path: Path) -> None:
    utc = SequenceClock(
        [
            datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 14, 10, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 14, 10, 0, 2, tzinfo=timezone.utc),
            datetime(2026, 8, 14, 10, 0, 3, tzinfo=timezone.utc),
        ]
    )
    monotonic = SequenceClock([20.0, 21.0, 22.0, 23.0])
    recorder = TimingRecorder(tmp_path, utc_now=utc, monotonic=monotonic)

    with recorder.span(level="run", name="clean"):
        with pytest.raises(ValueError, match="broken"):
            with recorder.span(level="stage", name="evolution"):
                raise ValueError("broken")
    summary = recorder.finalize()

    assert summary.run.status == "completed"
    assert summary.stages[0].status == "failed"
    assert summary.stages[0].error_type == "ValueError"


def test_task_level_requires_task_id_and_preserves_reuse_metadata(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError):
        TimingSpan(
            level="task",
            name="seed",
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
            duration_seconds=0,
            status="completed",
        )
    recorder = TimingRecorder(tmp_path)

    with recorder.span(level="run", name="clean"):
        with recorder.span(
            level="task",
            name="clean",
            task_id="test",
            metadata={"reused_from_stage": "seed"},
        ):
            pass
    summary = recorder.finalize()

    assert summary.tasks[0].task_id == "test"
    assert summary.tasks[0].metadata == {"reused_from_stage": "seed"}
