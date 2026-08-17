"""Resource-aware subprocess scheduling with immutable attempt directories."""

from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal, Sequence
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from rsebench.contracts import StrictModel
from rsebench.evidence import canonical_hash
from rsebench.experiments.contracts import (
    ExperimentIdentity,
    build_attempt_identity,
)
from rsebench.hashing import sha256_file


class UnitState(str, Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    interrupted = "interrupted"
    invalid = "invalid"


class ScheduledUnit(StrictModel):
    key: str = Field(min_length=1)
    experiment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: ExperimentIdentity | None = None
    command: list[str] = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    mutable_resource_keys: list[str] = Field(default_factory=list)
    adapter_key: str = Field(min_length=1)
    adapter_max_parallel: int = Field(default=1, ge=1)
    source_dir: str | None = None
    source_mode: Literal["read_only", "copy_on_run"] = "read_only"

    @field_validator("mutable_resource_keys")
    @classmethod
    def unique_resources(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("mutable resource keys must not be empty")
        if len(value) != len(set(value)):
            raise ValueError("mutable resource keys must be unique")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> "ScheduledUnit":
        if self.identity is not None and self.identity.experiment_id != self.experiment_id:
            raise ValueError("scheduled identity differs from experiment_id")
        if self.source_mode == "copy_on_run" and not self.source_dir:
            raise ValueError("copy_on_run requires a method source directory")
        return self


CommandRunner = Callable[..., Any]
ContainerCleaner = Callable[[str], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentScheduler:
    def __init__(
        self,
        *,
        run_root: Path | str,
        project_root: Path | str,
        max_parallel: int,
        command_runner: CommandRunner | None = None,
        container_cleaner: ContainerCleaner | None = None,
        status_metadata: dict[str, Any] | None = None,
    ) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be positive")
        self.run_root = Path(run_root).resolve()
        self.project_root = Path(project_root).resolve()
        self.max_parallel = max_parallel
        self.status_metadata = dict(status_metadata or {})
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.status_path = self.run_root / "matrix_status.json"
        self.events_path = self.run_root / "events.jsonl"
        self._command_runner = command_runner
        self._container_cleaner = container_cleaner or self._default_container_cleaner
        self._state_lock = threading.RLock()
        self._resource_locks: dict[str, threading.Lock] = {}
        self._adapter_semaphores: dict[str, threading.Semaphore] = {}
        self._active_processes: dict[str, subprocess.Popen[str]] = {}
        self._active_lock = threading.Lock()
        self._interrupt_event = threading.Event()
        self._read_only_source_snapshots: dict[str, str] = {}
        status_exists = self.status_path.is_file()
        self._status = self._load_status()
        if not status_exists:
            self._write_status()

    def _load_status(self) -> dict[str, Any]:
        if not self.status_path.is_file():
            return {
                "schema_version": "rsebench.scheduler-status.v1",
                "metadata": self.status_metadata,
                "updated_at": _utc_now(),
                "units": {},
            }
        payload = json.loads(self.status_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("units"), dict):
            raise ValueError(f"invalid scheduler status: {self.status_path}")
        stored_metadata = payload.get("metadata")
        if not isinstance(stored_metadata, dict):
            raise ValueError(f"invalid scheduler metadata: {self.status_path}")
        priority = ["config_hash", "git_head"]
        keys = [*priority, *(key for key in self.status_metadata if key not in priority)]
        for key in keys:
            if key not in self.status_metadata:
                continue
            value = self.status_metadata[key]
            if stored_metadata.get(key) != value:
                label = key.replace("_", " ")
                raise RuntimeError(
                    f"scheduler resume {label} differs ({key} differs) from current run"
                )
        return payload

    def _write_status(self) -> None:
        self._status["updated_at"] = _utc_now()
        encoded = (
            json.dumps(self._status, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        temporary = self.status_path.with_suffix(".json.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, self.status_path)

    def _append_event(self, payload: dict[str, Any]) -> None:
        event = {"timestamp": _utc_now(), **payload}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _unit_directory(key: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", key).strip("-") or "unit"
        return f"{slug}-{canonical_hash(key)[:8]}"

    @staticmethod
    def _result_identity(path: Path) -> str | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        identity = payload.get("identity")
        if not isinstance(identity, dict):
            return None
        value = identity.get("experiment_id")
        return str(value) if value is not None else None

    def _resumable(self, unit: ScheduledUnit) -> bool:
        row = self._status["units"].get(unit.key)
        if not isinstance(row, dict):
            return False
        if row.get("state") != UnitState.completed.value:
            return False
        if row.get("experiment_id") != unit.experiment_id:
            return False
        attempts = row.get("attempts") or []
        if not attempts:
            return False
        result_path = Path(str(attempts[-1].get("result_path") or ""))
        return self._result_identity(result_path) == unit.experiment_id

    def _new_attempt(self, unit: ScheduledUnit) -> dict[str, Any]:
        previous = self._status["units"].get(unit.key, {}).get("attempts", [])
        attempt_number = len(previous) + 1
        attempt_id = uuid4()
        attempt_dir = (
            self.run_root
            / "attempts"
            / self._unit_directory(unit.key)
            / f"{attempt_number:04d}-{attempt_id}"
        )
        attempt_dir.mkdir(parents=True, exist_ok=False)
        attempt = {
            "attempt_id": str(attempt_id),
            "attempt_number": attempt_number,
            "attempt_dir": str(attempt_dir),
            "state": UnitState.queued.value,
            "queued_at": _utc_now(),
        }
        self._status["units"][unit.key] = {
            "key": unit.key,
            "experiment_id": unit.experiment_id,
            "state": UnitState.queued.value,
            "attempts": [*previous, attempt],
        }
        self._append_event(
            {
                "key": unit.key,
                "experiment_id": unit.experiment_id,
                "attempt_id": str(attempt_id),
                "state": UnitState.queued.value,
            }
        )
        self._write_status()
        return attempt

    def _transition(
        self,
        unit: ScheduledUnit,
        attempt_id: str,
        state: UnitState,
        **updates: Any,
    ) -> None:
        with self._state_lock:
            row = self._status["units"][unit.key]
            attempt = next(
                item for item in row["attempts"] if item["attempt_id"] == attempt_id
            )
            attempt.update(state=state.value, **updates)
            row["state"] = state.value
            row["experiment_id"] = unit.experiment_id
            self._append_event(
                {
                    "key": unit.key,
                    "experiment_id": unit.experiment_id,
                    "attempt_id": attempt_id,
                    "state": state.value,
                    **updates,
                }
            )
            self._write_status()

    @staticmethod
    def _isolated_command(command: list[str], output_root: Path) -> list[str]:
        isolated = list(command)
        if "--output-root" in isolated:
            index = isolated.index("--output-root")
            if index + 1 >= len(isolated):
                raise ValueError("--output-root lacks a value")
            isolated[index + 1] = str(output_root)
        else:
            isolated.extend(["--output-root", str(output_root)])
        return isolated

    def _environment(
        self,
        attempt_dir: Path,
        attempt_id: str,
        attempt_number: int,
        unit: ScheduledUnit,
        source_path: Path | None,
    ) -> dict[str, str]:
        environment = dict(os.environ)
        paths = {
            "TMPDIR": attempt_dir / "tmp",
            "XDG_CACHE_HOME": attempt_dir / "cache/xdg",
            "HF_HOME": attempt_dir / "cache/huggingface",
            "RSEBENCH_OUTPUT_ROOT": attempt_dir / "runner",
            "RSEBENCH_TOKEN_LEDGER": attempt_dir / "token_usage",
            "RSEBENCH_WORKSPACE_ROOT": attempt_dir / "workspace",
            "RSEBENCH_NOISY_ROOT": attempt_dir / "noisy",
            "RSEBENCH_MUTATION_AUDIT_ROOT": attempt_dir / "mutation_audit",
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        environment.update({name: str(path) for name, path in paths.items()})
        environment["PYTHONPATH"] = str(self.project_root / "src")
        environment["RSEBENCH_ATTEMPT_ID"] = attempt_id
        environment["RSEBENCH_EXPERIMENT_ID"] = unit.experiment_id
        environment["RSEBENCH_CONTAINER_PREFIX"] = f"rsebench-{attempt_id}"
        environment["RSEBENCH_SOURCE_MODE"] = unit.source_mode
        if source_path is not None:
            environment["RSEBENCH_METHOD_SOURCE"] = str(source_path)
        if unit.identity is not None:
            attempt = build_attempt_identity(
                unit.identity,
                attempt_number=attempt_number,
                attempt_id=attempt_id,
            )
            identity_path = attempt_dir / "runtime_identity.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "identity": unit.identity.model_dump(mode="json"),
                        "attempt": attempt.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            environment["RSEBENCH_IDENTITY_PATH"] = str(identity_path)
        return environment

    @staticmethod
    def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
        ignored = {
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            "outputs",
            "jobs",
        }
        return set(names).intersection(ignored)

    def _prepare_source(
        self,
        unit: ScheduledUnit,
        attempt_dir: Path,
    ) -> Path | None:
        if unit.source_dir is None:
            return None
        source = Path(unit.source_dir).resolve()
        try:
            source.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(f"method source escapes project root: {source}") from exc
        if not source.is_dir():
            raise FileNotFoundError(f"method source is missing: {source}")
        if unit.source_mode == "read_only":
            return source
        destination = attempt_dir / "workspace" / "method-source"
        shutil.copytree(
            source,
            destination,
            symlinks=True,
            ignore=self._copy_ignore,
        )
        return destination

    @staticmethod
    def _source_snapshot(source: Path) -> str:
        ignored = {
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
        }
        rows: list[dict[str, str]] = []
        for candidate in sorted(source.rglob("*")):
            if ignored.intersection(candidate.relative_to(source).parts):
                continue
            if candidate.is_symlink():
                rows.append(
                    {
                        "path": candidate.relative_to(source).as_posix(),
                        "kind": "symlink",
                        "target": os.readlink(candidate),
                    }
                )
            elif candidate.is_file():
                rows.append(
                    {
                        "path": candidate.relative_to(source).as_posix(),
                        "kind": "file",
                        "sha256": sha256_file(candidate),
                    }
                )
        return canonical_hash(rows)

    def _default_run(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        unit: ScheduledUnit,
        attempt_id: str,
    ) -> subprocess.CompletedProcess[str]:
        del unit
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        with self._active_lock:
            self._active_processes[attempt_id] = process
        try:
            stdout, stderr = process.communicate()
        finally:
            with self._active_lock:
                self._active_processes.pop(attempt_id, None)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    @staticmethod
    def _reported_result(stdout: str, attempt_dir: Path) -> Path | None:
        for line in stdout.splitlines():
            candidate = Path(line.strip())
            if not candidate.is_absolute():
                continue
            result = candidate / "result.json"
            if result.is_file():
                try:
                    result.resolve().relative_to(attempt_dir.resolve())
                except ValueError:
                    continue
                return result.resolve()
        candidates = sorted((attempt_dir / "runner").rglob("result.json"))
        return candidates[0].resolve() if len(candidates) == 1 else None

    def _execute(self, unit: ScheduledUnit, attempt: dict[str, Any]) -> None:
        attempt_id = str(attempt["attempt_id"])
        attempt_dir = Path(attempt["attempt_dir"])
        queued_monotonic = time.monotonic()
        semaphore = self._adapter_semaphores[unit.adapter_key]
        resource_locks = [
            self._resource_locks[key] for key in sorted(unit.mutable_resource_keys)
        ]
        with ExitStack() as stack:
            stack.enter_context(semaphore)
            for lock in resource_locks:
                stack.enter_context(lock)
            if self._interrupt_event.is_set():
                self._transition(
                    unit,
                    attempt_id,
                    UnitState.interrupted,
                    ended_at=_utc_now(),
                    error_type="SchedulerInterrupt",
                    error="scheduler interrupted before launcher start",
                )
                return
            started_monotonic = time.monotonic()
            self._transition(
                unit,
                attempt_id,
                UnitState.running,
                started_at=_utc_now(),
                queue_duration_seconds=started_monotonic - queued_monotonic,
            )
            runner_root = attempt_dir / "runner"
            command = self._isolated_command(unit.command, runner_root)
            try:
                source_path = self._prepare_source(unit, attempt_dir)
                source_snapshot = (
                    self._read_only_source_snapshots.get(str(source_path))
                    if source_path is not None and unit.source_mode == "read_only"
                    else None
                )
                environment = self._environment(
                    attempt_dir,
                    attempt_id,
                    int(attempt["attempt_number"]),
                    unit,
                    source_path,
                )
                if self._command_runner is None:
                    completed = self._default_run(
                        command,
                        cwd=self.project_root,
                        env=environment,
                        unit=unit,
                        attempt_id=attempt_id,
                    )
                else:
                    completed = self._command_runner(
                        command,
                        cwd=self.project_root,
                        env=environment,
                        unit=unit,
                    )
                stdout = str(completed.stdout or "")
                stderr = str(completed.stderr or "")
                (attempt_dir / "stdout.log").write_text(stdout, encoding="utf-8")
                (attempt_dir / "stderr.log").write_text(stderr, encoding="utf-8")
                duration = time.monotonic() - started_monotonic
                common = {
                    "ended_at": _utc_now(),
                    "run_duration_seconds": duration,
                    "returncode": int(completed.returncode),
                }
                if self._interrupt_event.is_set():
                    self._transition(
                        unit,
                        attempt_id,
                        UnitState.interrupted,
                        **common,
                        error_type="SchedulerInterrupt",
                        error="scheduler interrupted during launcher execution",
                    )
                    return
                if (
                    source_snapshot is not None
                    and source_path is not None
                    and self._source_snapshot(source_path) != source_snapshot
                ):
                    self._transition(
                        unit,
                        attempt_id,
                        UnitState.invalid,
                        **common,
                        error="read-only method source changed during launcher execution",
                    )
                    return
                if completed.returncode != 0:
                    self._transition(
                        unit,
                        attempt_id,
                        UnitState.failed,
                        **common,
                        error="launcher returned non-zero status",
                    )
                    return
                result_path = self._reported_result(stdout, attempt_dir)
                if result_path is None:
                    self._transition(
                        unit,
                        attempt_id,
                        UnitState.invalid,
                        **common,
                        error="launcher produced no isolated result",
                    )
                    return
                if self._result_identity(result_path) != unit.experiment_id:
                    self._transition(
                        unit,
                        attempt_id,
                        UnitState.invalid,
                        **common,
                        result_path=str(result_path),
                        error="result experiment identity mismatch",
                    )
                    return
                self._transition(
                    unit,
                    attempt_id,
                    UnitState.completed,
                    **common,
                    result_path=str(result_path),
                    result_hash=sha256_file(result_path),
                )
            except BaseException as exc:
                state = (
                    UnitState.interrupted
                    if self._interrupt_event.is_set()
                    or isinstance(exc, (KeyboardInterrupt, SystemExit))
                    else UnitState.failed
                )
                self._transition(
                    unit,
                    attempt_id,
                    state,
                    ended_at=_utc_now(),
                    run_duration_seconds=time.monotonic() - started_monotonic,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                if state == UnitState.interrupted:
                    raise

    def _terminate_active(self) -> None:
        with self._active_lock:
            processes = list(self._active_processes.values())
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    continue
        deadline = time.monotonic() + 5.0
        while any(process.poll() is None for process in processes):
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    continue

    @staticmethod
    def _default_container_cleaner(attempt_id: str) -> None:
        """Remove only containers registered to one scheduler attempt."""

        try:
            listed = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=rsebench.attempt_id={attempt_id}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        container_ids = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        if listed.returncode != 0 or not container_ids:
            return
        try:
            subprocess.run(
                ["docker", "rm", "-f", *container_ids],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return

    def _mark_interrupted(
        self,
        attempts: Sequence[tuple[ScheduledUnit, dict[str, Any]]],
    ) -> None:
        for unit, attempt in attempts:
            attempt_id = str(attempt["attempt_id"])
            with self._state_lock:
                row = self._status["units"].get(unit.key, {})
                current = next(
                    (
                        item
                        for item in row.get("attempts", [])
                        if item.get("attempt_id") == attempt_id
                    ),
                    None,
                )
                if not isinstance(current, dict) or current.get("state") not in {
                    UnitState.queued.value,
                    UnitState.running.value,
                }:
                    continue
                self._transition(
                    unit,
                    attempt_id,
                    UnitState.interrupted,
                    ended_at=_utc_now(),
                    error_type="SchedulerInterrupt",
                    error="scheduler interrupted",
                )

    def _cleanup_skilllearn_containers(
        self,
        attempts: Sequence[tuple[ScheduledUnit, dict[str, Any]]],
    ) -> None:
        for unit, attempt in attempts:
            is_skilllearn = unit.adapter_key.startswith("skilllearn") or any(
                key.startswith("docker:skilllearn")
                for key in unit.mutable_resource_keys
            )
            if not is_skilllearn:
                continue
            attempt_id = str(attempt["attempt_id"])
            try:
                self._container_cleaner(attempt_id)
            except Exception as exc:
                self._append_event(
                    {
                        "key": unit.key,
                        "attempt_id": attempt_id,
                        "state": UnitState.interrupted.value,
                        "cleanup_error_type": type(exc).__name__,
                        "cleanup_error": str(exc),
                    }
                )

    def _rows(self, units: Sequence[ScheduledUnit]) -> list[dict[str, Any]]:
        return [
            dict(
                self._status["units"].get(
                    unit.key,
                    {
                        "key": unit.key,
                        "experiment_id": unit.experiment_id,
                        "state": UnitState.pending.value,
                        "attempts": [],
                    },
                )
            )
            for unit in units
        ]

    def run(
        self,
        units: Sequence[ScheduledUnit],
        *,
        max_new_units: int | None = None,
    ) -> list[dict[str, Any]]:
        if max_new_units is not None and max_new_units < 1:
            raise ValueError("max_new_units must be positive")
        if len({unit.key for unit in units}) != len(units):
            raise ValueError("scheduled unit keys must be unique")
        self._interrupt_event.clear()
        adapter_limits: dict[str, int] = {}
        self._read_only_source_snapshots = {}
        for unit in units:
            previous = adapter_limits.setdefault(
                unit.adapter_key, unit.adapter_max_parallel
            )
            if previous != unit.adapter_max_parallel:
                raise ValueError(f"inconsistent adapter limit: {unit.adapter_key}")
            for key in unit.mutable_resource_keys:
                self._resource_locks.setdefault(key, threading.Lock())
            if unit.source_dir and unit.source_mode == "read_only":
                source = Path(unit.source_dir).resolve()
                try:
                    source.relative_to(self.project_root)
                except ValueError as exc:
                    raise ValueError(
                        f"method source escapes project root: {source}"
                    ) from exc
                if not source.is_dir():
                    raise FileNotFoundError(f"method source is missing: {source}")
                source_key = str(source)
                if source_key not in self._read_only_source_snapshots:
                    self._read_only_source_snapshots[source_key] = (
                        self._source_snapshot(source)
                    )
        self._adapter_semaphores = {
            key: threading.Semaphore(limit) for key, limit in adapter_limits.items()
        }

        pending = [unit for unit in units if not self._resumable(unit)]
        if max_new_units is not None:
            pending = pending[:max_new_units]
        attempts: list[tuple[ScheduledUnit, dict[str, Any]]] = []
        with self._state_lock:
            for unit in pending:
                attempts.append((unit, self._new_attempt(unit)))
        executor = ThreadPoolExecutor(max_workers=self.max_parallel)
        futures = {
            executor.submit(self._execute, unit, attempt): unit
            for unit, attempt in attempts
        }
        previous_sigterm = None
        can_set_signal = threading.current_thread() is threading.main_thread()
        if can_set_signal:
            previous_sigterm = signal.getsignal(signal.SIGTERM)

            def _interrupt(signum, frame):
                del signum, frame
                raise KeyboardInterrupt

            signal.signal(signal.SIGTERM, _interrupt)
        try:
            for future in as_completed(futures):
                future.result()
        except KeyboardInterrupt:
            self._interrupt_event.set()
            self._terminate_active()
            for future in futures:
                future.cancel()
            self._mark_interrupted(attempts)
            self._cleanup_skilllearn_containers(attempts)
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        finally:
            if can_set_signal and previous_sigterm is not None:
                signal.signal(signal.SIGTERM, previous_sigterm)
        executor.shutdown(wait=True)
        return self._rows(units)


__all__ = ["ExperimentScheduler", "ScheduledUnit", "UnitState"]
