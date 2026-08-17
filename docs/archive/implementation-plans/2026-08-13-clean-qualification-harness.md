# Clean Qualification Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clean-only self-evolution runner, typed execution audit, qualification decision, report, and 2/3 aggregate without constructing or dispatching a noisy arm.

**Architecture:** A portable `CleanEvolutionSplitManifest` stores only clean tasks. A narrow bridge creates the paired-shaped in-memory view required by existing executors, but `CleanEvolutionRunner` builds and executes only one `arm="clean"` manifest and never creates a `noisy/` directory. Executors publish a typed `EvolutionExecutionAudit`; the runner combines that audit with seed/evolved clean-test results and optional OfficeQA runtime thresholds into one immutable qualification decision.

**Tech Stack:** Python 3.13, Pydantic 2, pytest 8, existing RSEBench executors and token ledger.

## Global Constraints

- Formal method seeds are exactly `20260813`, `20260814`, and `20260815`.
- Persisted clean manifests contain no `noisy` field, noise record, or N1 payload.
- The runner executes seed evaluation, one clean evolution arm, and evolved clean-test evaluation only.
- Seed floor and ceiling never stop clean evolution.
- A successful run requires 100% task coverage, a semantic artifact update, at least one native accepted update, and clean gain greater than or equal to zero.
- Provider, tool, parser, protocol, timeout, and infrastructure failures are typed failures, never ordinary zero scores.
- All model calls use `deepseek-v4-flash`, temperature 0, and thinking disabled.
- Do not change `PairedEvolutionRunner` behavior or existing paired result schemas.

---

### Task 1: Define the portable clean split and execution audit

**Files:**
- Create: `src/rsebench/evolution/clean_contracts.py`
- Modify: `src/rsebench/evolution/runner.py`
- Create: `tests/evolution/test_clean_contracts.py`

**Interfaces:**
- Produces: `CleanEvolutionSplitManifest`, `EvolutionExecutionAudit`, `CleanQualificationPolicy`, and `CleanQualificationDecision`.
- Extends: `EvolutionArtifact.execution_audit: EvolutionExecutionAudit | None` with a backwards-compatible `None` default.
- Consumes later: all baseline executors populate `EvolutionExecutionAudit`; `CleanEvolutionRunner` refuses qualification when it is absent.

- [ ] **Step 1: Write failing clean-contract tests**

Add these tests to `tests/evolution/test_clean_contracts.py`:

```python
import hashlib

import pytest

from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_contracts import (
    CleanEvolutionSplitManifest,
    CleanQualificationPolicy,
    EvolutionExecutionAudit,
)


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="document",
        prompt=task_id,
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
    )


def test_clean_split_contains_only_clean_tasks_and_rejects_overlap() -> None:
    split = CleanEvolutionSplitManifest(
        benchmark="fixture",
        domain="document",
        seed=7,
        source_hash="a" * 64,
        train=[_task("train")],
        validation=[_task("validation")],
        clean_test=[_task("test")],
        metadata={"config_version": "clean-qualification-v1"},
    )
    payload = split.model_dump(mode="json")
    assert set(payload) == {
        "benchmark", "domain", "seed", "source_hash",
        "train", "validation", "clean_test", "metadata",
    }
    assert "noisy" not in split.model_dump_json()

    with pytest.raises(ValueError, match="must be disjoint"):
        CleanEvolutionSplitManifest(
            benchmark="fixture",
            domain="document",
            seed=7,
            source_hash="a" * 64,
            train=[_task("train")],
            validation=[_task("validation")],
            clean_test=[_task("train")],
        )


def test_execution_audit_requires_unique_exact_task_ids() -> None:
    audit = EvolutionExecutionAudit(
        train_task_ids=["t1", "t2"],
        validation_task_ids=["v1"],
        accepted_update_count=1,
    )
    assert audit.accepted_update_count == 1
    with pytest.raises(ValueError, match="duplicate"):
        EvolutionExecutionAudit(
            train_task_ids=["t1", "t1"],
            validation_task_ids=["v1"],
            accepted_update_count=1,
        )


def test_office_runtime_policy_validates_thresholds() -> None:
    policy = CleanQualificationPolicy(
        min_parseable_answer_rate=0.80,
        max_systemic_failure_rate=0.05,
    )
    assert policy.min_parseable_answer_rate == 0.80
```

- [ ] **Step 2: Run the tests and confirm the module is missing**

Run:

```bash
pytest tests/evolution/test_clean_contracts.py -v
```

Expected: collection fails with `ModuleNotFoundError: rsebench.evolution.clean_contracts`.

- [ ] **Step 3: Add the exact clean contract models**

Create `src/rsebench/evolution/clean_contracts.py` with these public models and validators:

```python
from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from rsebench.contracts import StrictModel, TaskManifest


class CleanEvolutionSplitManifest(StrictModel):
    benchmark: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    seed: int
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    train: list[TaskManifest]
    validation: list[TaskManifest]
    clean_test: list[TaskManifest]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_isolation(self) -> "CleanEvolutionSplitManifest":
        ids = {
            "train": [task.task_id for task in self.train],
            "validation": [task.task_id for task in self.validation],
            "clean_test": [task.task_id for task in self.clean_test],
        }
        flattened = ids["train"] + ids["validation"] + ids["clean_test"]
        if len(flattened) != len(set(flattened)):
            raise ValueError("train, validation, and clean_test task IDs must be disjoint")
        for task in self.train + self.validation + self.clean_test:
            if task.benchmark != self.benchmark or task.domain != self.domain:
                raise ValueError("task benchmark/domain does not match clean split")
        if not self.train or not self.validation or not self.clean_test:
            raise ValueError("clean qualification requires non-empty train, validation, and clean_test")
        return self


class EvolutionExecutionAudit(StrictModel):
    train_task_ids: list[str]
    validation_task_ids: list[str]
    accepted_update_count: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "EvolutionExecutionAudit":
        for name, values in (
            ("train", self.train_task_ids),
            ("validation", self.validation_task_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {name} task IDs in execution audit")
        return self


class CleanQualificationPolicy(StrictModel):
    min_parseable_answer_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    max_systemic_failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class CleanQualificationDecision(StrictModel):
    execution_coverage_passed: bool
    artifact_updated: bool
    accepted_update_count: int = Field(ge=0)
    nondegrading: bool
    runtime_gates_passed: bool
    seed_score: float
    evolved_score: float
    clean_gain: float
    strictly_positive_gain: bool
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)
```

In `src/rsebench/evolution/runner.py`, import `EvolutionExecutionAudit` and add this field to `EvolutionArtifact`:

```python
execution_audit: EvolutionExecutionAudit | None = None
```

- [ ] **Step 4: Run focused and compatibility tests**

Run:

```bash
pytest tests/evolution/test_clean_contracts.py tests/evolution/test_runner.py -v
```

Expected: all tests pass; existing fixture artifacts remain valid because `execution_audit` defaults to `None`.

- [ ] **Step 5: Commit the contracts**

```bash
git add src/rsebench/evolution/clean_contracts.py src/rsebench/evolution/runner.py tests/evolution/test_clean_contracts.py
git commit -m "feat: define clean qualification contracts"
```

---

### Task 2: Bridge clean manifests to existing executors without a noisy arm

**Files:**
- Create: `src/rsebench/evolution/clean_bridge.py`
- Modify: `src/rsebench/evolution/pairs.py`
- Modify: `src/rsebench/core1/dataset.py`
- Create: `tests/evolution/test_clean_bridge.py`
- Modify: `tests/core1/test_dataset.py`

**Interfaces:**
- Produces: `build_clean_runtime_split(split: CleanEvolutionSplitManifest) -> EvolutionSplitManifest`.
- Produces: `build_clean_arm_manifest(split: EvolutionSplitManifest, *, method: str, method_seed: int, seed_skill_hash: str, parameters: dict | None = None) -> EvolutionArmManifest`.
- Produces: `make_clean_split_paths_portable(...)` and `resolve_clean_split_paths(...)` with the same declared-root safety checks as paired manifests.
- The transient runtime split duplicates each clean task only in memory to satisfy current executor interfaces. It is never written to disk and contains no N1 text.

- [ ] **Step 1: Write the failing bridge test**

Add `tests/evolution/test_clean_bridge.py`:

```python
import hashlib

from rsebench.contracts import TaskManifest
from rsebench.evolution.clean_bridge import build_clean_runtime_split
from rsebench.evolution.clean_contracts import CleanEvolutionSplitManifest
from rsebench.evolution.pairs import build_clean_arm_manifest


def _task(task_id: str) -> TaskManifest:
    return TaskManifest(
        task_id=task_id,
        benchmark="fixture",
        domain="document",
        prompt=f"clean {task_id}",
        source_hash=hashlib.sha256(task_id.encode()).hexdigest(),
    )


def test_clean_bridge_builds_only_a_clean_arm() -> None:
    clean = CleanEvolutionSplitManifest(
        benchmark="fixture",
        domain="document",
        seed=7,
        source_hash="a" * 64,
        train=[_task("train")],
        validation=[_task("validation")],
        clean_test=[_task("test")],
    )
    runtime = build_clean_runtime_split(clean)
    arm = build_clean_arm_manifest(
        runtime,
        method="fixture",
        method_seed=11,
        seed_skill_hash="b" * 64,
        parameters={"qualification_version": "v1"},
    )

    assert arm.arm == "clean"
    assert arm.train[0].noise_id is None
    assert runtime.train[0].clean == runtime.train[0].noisy
    assert runtime.train[0].noise.operator == "clean_qualification_identity"
```

- [ ] **Step 2: Run the test and confirm both functions are absent**

```bash
pytest tests/evolution/test_clean_bridge.py -v
```

Expected: import failure for `rsebench.evolution.clean_bridge`.

- [ ] **Step 3: Implement the transient bridge and clean-arm constructor**

Create `src/rsebench/evolution/clean_bridge.py`. Build one identity
`EvolutionTaskPair` per train/validation task using `NoiseManifest` with
`operator="clean_qualification_identity"`, `channel="C1"`, `mechanism="M1"`,
`timing="evolution"`, and identical clean/noisy hashes. Preserve the clean
split's benchmark, domain, seed, source hash, order, and clean test.

Add `build_clean_arm_manifest` to `src/rsebench/evolution/pairs.py` by extracting
the shared fields currently duplicated inside `build_arm_manifests`. The clean
function must call `_pair_refs(split.train, "clean")` and
`_pair_refs(split.validation, "clean")` exactly once and must not instantiate
an `arm="noisy"` object.

Add clean-manifest path mapping to `src/rsebench/core1/dataset.py`. Map every
task in `train`, `validation`, and `clean_test` through the existing
`_map_task_paths` function. Recompute `source_hash` only when encoding portable
paths, using a payload containing benchmark, domain, seed, all three ordered
task lists, and metadata. Add a round-trip test in `tests/core1/test_dataset.py`
that encodes an artifact path under each declared root, asserts no `/home/`
substring remains, resolves it, and asserts task IDs and source hash are
unchanged.

- [ ] **Step 4: Prove the paired constructor is unchanged**

```bash
pytest tests/evolution/test_clean_bridge.py tests/evolution/test_pairs.py tests/core1/test_dataset.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the bridge**

```bash
git add src/rsebench/evolution/clean_bridge.py src/rsebench/evolution/pairs.py src/rsebench/core1/dataset.py tests/evolution/test_clean_bridge.py tests/core1/test_dataset.py
git commit -m "feat: bridge clean-only evolution manifests"
```

---

### Task 3: Implement the append-only clean runner and report

**Files:**
- Create: `src/rsebench/evolution/clean_runner.py`
- Create: `src/rsebench/evolution/clean_report.py`
- Create: `tests/evolution/test_clean_runner.py`

**Interfaces:**
- Produces: `CleanEvolutionRunner.run(...) -> CleanEvolutionResult`.
- Persists: `split_manifest.json`, `clean/arm_manifest.json`, seed/evolved evaluations, `qualification.json`, `result.json`, `report.md`, and token artifacts.
- Failure boundary: writes `failure.json` and token artifacts before raising `CleanQualificationRunError(run_dir=...)`.

- [ ] **Step 1: Write a failing happy-path test that forbids noisy output**

Use a fixture executor whose artifact includes:

```python
execution_audit=EvolutionExecutionAudit(
    train_task_ids=["train"],
    validation_task_ids=["validation"],
    accepted_update_count=1,
)
```

Then assert:

```python
result = CleanEvolutionRunner(executor).run(
    method="fixture",
    split=split,
    seed_skill_path=seed,
    method_seed=20260813,
    parameters={"model": "deepseek-v4-flash", "thinking": "disabled"},
    output_root=tmp_path / "runs",
    policy=CleanQualificationPolicy(),
)

run_dir = Path(result.run_dir)
assert executor.evaluate_calls == ["seed", "clean"]
assert [call.arm for call in executor.evolve_calls] == ["clean"]
assert result.qualification.passed is True
assert result.qualification.clean_gain == 0.5
assert not (run_dir / "noisy").exists()
assert "noisy" not in (run_dir / "split_manifest.json").read_text()
assert (run_dir / "qualification.json").is_file()
assert (run_dir / "result.json").is_file()
assert (run_dir / "report.md").is_file()
```

Add separate tests proving qualification fails when the audit is absent, one
train ID is missing, accepted count is zero, the artifact hash is unchanged,
clean gain is negative, or OfficeQA diagnostics violate either runtime gate.

- [ ] **Step 2: Run the clean-runner tests and verify failure**

```bash
pytest tests/evolution/test_clean_runner.py -v
```

Expected: import failure for `CleanEvolutionRunner`.

- [ ] **Step 3: Implement `CleanEvolutionResult` and the runner**

Define `CleanEvolutionResult` with these exact fields:

```python
class CleanEvolutionResult(StrictModel):
    run_dir: str
    method: str
    method_seed: int
    seed_skill_hash: str
    clean_skill_hash: str
    seed_evaluation: EvaluationResult
    clean_evaluation: EvaluationResult
    clean_artifact: EvolutionArtifact
    qualification: CleanQualificationDecision
    token_usage: dict[str, Any]
```

The runner must:

1. create a timestamped run directory;
2. configure token accounting;
3. write only the clean manifest;
4. copy the seed into `seed/` and `clean/`;
5. evaluate the seed with `stage="seed"`;
6. build only `build_clean_arm_manifest(...)`;
7. call `executor.evolve(...)` once;
8. verify seed immutability and artifact hash;
9. evaluate the evolved artifact with `stage="clean"`, reusing the seed result
   only when hashes are identical;
10. compare audit task-ID sets with the exact train/validation ID sets, while
    separately retaining manifest order, and compare evaluation IDs with the
    clean-test ID set;
11. fail with `execution_failure` when either evaluation reports a non-empty
    `diagnostics.execution_failures` mapping, then apply the optional
    parseability/systemic-failure thresholds;
12. write a complete `CleanQualificationDecision` and token summary.

`failure_reasons` uses only these stable values:

```python
[
    "missing_execution_audit",
    "train_execution_coverage",
    "validation_execution_coverage",
    "clean_test_execution_coverage",
    "artifact_unchanged",
    "no_accepted_update",
    "clean_score_decreased",
    "parseable_answer_rate",
    "systemic_failure_rate",
    "execution_failure",
]
```

Catch ordinary exceptions only after the run directory exists. Persist
`failure.json` containing exception class and message, write token artifacts,
then raise `CleanQualificationRunError` with the run directory. Do not catch
`KeyboardInterrupt` or `SystemExit`.

- [ ] **Step 4: Implement the clean report**

`render_clean_report(result)` must render method, method seed, task counts,
seed score, evolved score, clean gain, artifact-updated flag, accepted update
count, each runtime gate, final qualification status, failure reasons, billed
tokens, logical tokens, and observed token coverage. The first heading is
`# Clean Baseline Qualification Result`.

- [ ] **Step 5: Run focused tests**

```bash
pytest tests/evolution/test_clean_runner.py tests/evolution/test_runner.py -v
```

Expected: all tests pass and paired-runner assertions remain unchanged.

- [ ] **Step 6: Commit the clean runner**

```bash
git add src/rsebench/evolution/clean_runner.py src/rsebench/evolution/clean_report.py tests/evolution/test_clean_runner.py
git commit -m "feat: run clean-only baseline qualification"
```

---

### Task 4: Aggregate three-seed and SkillLearn family decisions

**Files:**
- Create: `scripts/aggregate_clean_qualification.py`
- Create: `tests/validation/test_aggregate_clean_qualification.py`

**Interfaces:**
- Produces: `build_aggregate(run_root: Path) -> dict[str, Any]`.
- Counts Spreadsheet, OfficeQA, and WebShop as qualified at 2/3 successful method seeds.
- Counts each SkillLearn family at 2/3 and SkillLearnBench at 4/8 qualified families.
- Produces: `all_benchmarks_qualified`, the sole N1 barrier flag.

- [ ] **Step 1: Write failing aggregate tests**

Create fixture `result.json` files with explicit `method_seed`, benchmark,
family metadata, and `qualification.passed`. Assert:

```python
payload = build_aggregate(run_root)
assert payload["benchmarks"]["spreadsheetbench_verified"]["passed_runs"] == 2
assert payload["benchmarks"]["spreadsheetbench_verified"]["qualified"] is True
assert payload["skilllearn"]["families"]["offer-letter-generator"]["qualified"] is True
assert payload["skilllearn"]["qualified_family_count"] == 4
assert payload["skilllearn"]["qualified"] is True
assert payload["all_benchmarks_qualified"] is True
```

Add a missing-run fixture and assert it remains `missing`, counts as a failed
replication, and cannot be omitted from the denominator.

- [ ] **Step 2: Run and confirm the aggregate script is absent**

```bash
pytest tests/validation/test_aggregate_clean_qualification.py -v
```

Expected: import failure for `scripts.aggregate_clean_qualification`.

- [ ] **Step 3: Implement deterministic aggregation**

Scan exactly these paths:

```text
RUN_ROOT/spreadsheetbench_verified/METHOD_SEED/RUN_ID/result.json
RUN_ROOT/officeqa_full/METHOD_SEED/RUN_ID/result.json
RUN_ROOT/webshop/METHOD_SEED/RUN_ID/result.json
RUN_ROOT/skilllearnbench/FAMILY/METHOD_SEED/RUN_ID/result.json
```

Require the fixed three-seed set. Reject duplicate completed results for the
same benchmark/family/config-version/seed instead of silently selecting the
latest. Globally deduplicate token events with `aggregate_token_usage_tree`.
Write schema version `rsebench.clean-qualification-aggregate.v1`.

- [ ] **Step 4: Run aggregate and ledger tests**

```bash
pytest tests/validation/test_aggregate_clean_qualification.py tests/usage/test_ledger.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the aggregate**

```bash
git add scripts/aggregate_clean_qualification.py tests/validation/test_aggregate_clean_qualification.py
git commit -m "feat: aggregate clean qualification decisions"
```

---

### Task 5: Verify the shared harness before baseline integration

**Files:**
- Modify only if verification exposes a defect in Tasks 1-4.

**Interfaces:**
- Provides the tested dependency required by the SkillOpt, WebShop, and SkillLearn plans.

- [ ] **Step 1: Run the complete evolution and validation suites**

```bash
pytest tests/evolution tests/validation -q
```

Expected: zero failures.

- [ ] **Step 2: Run formatting and secret checks**

```bash
git diff --check
rg -n '/home/|DEEPSEEK_API_KEY\s*[:=]\s*[^$]' src scripts tests benchmark configs -g '*.py' -g '*.json' -g '*.yaml'
```

Expected: `git diff --check` is silent; the secret scan finds no credential
value and no new persisted absolute home path.

- [ ] **Step 3: Inspect the branch diff**

```bash
git status --short
git log --oneline --max-count=8
```

Expected: only intentional harness commits are present and the worktree is
clean.
