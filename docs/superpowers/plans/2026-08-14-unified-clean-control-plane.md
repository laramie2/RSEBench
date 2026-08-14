# Unified Clean Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the implemented RSEBench pilot and baseline repairs into canonical `main`, add deterministic baseline/bootstrap identity, three-level timing, isolated parallel scheduling, two-level qualification, and release freezing, then rerun all four clean-v2 cells before N1–N4.

**Architecture:** Preserve upstream baselines as gitignored pinned clones with ordered replay patches. A new `rsebench.experiments` control layer owns identities, timing, scheduler state, qualification aggregation, and compact releases while existing baseline executors remain thin native adapters. All provider-backed work is deferred until provider-free preflight and failure-targeted canaries pass.

**Tech Stack:** Python 3.13 (supports Python 3.11+), Pydantic 2, Typer, PyYAML, pytest, Git, Docker for SkillLearn, DeepSeek OpenAI-compatible API.

## Global Constraints

- `main` is the sole canonical experiment and GitHub release branch.
- Baseline source stays outside Git in `methods/external/`; no vendoring and no submodules.
- SkillOpt revision is `47fe269d75d3def79ffd90236261d26d84868ae5`.
- SkillAdaptor revision is `b26d1ab5a798f07e53048b5ff509e8535e9fa228`.
- SkillLearnBench revision is `a0da045a8bf64b8a8ff20730c4d6ef10dc4e2c5b`.
- Formal method seeds are `20260813`, `20260814`, and `20260815`.
- All formal model calls use `deepseek-v4-flash`, temperature `0`, and thinking disabled.
- Clean test outcomes never enter reflection, artifact editing, candidate selection, validation, runtime calibration, or sample replacement.
- Every result records run-, stage-, and task-level UTC timestamps plus monotonic durations.
- A cell is `engineering_ready` at 2/3 engineering-valid seeds and `efficacy_ready` only when 2/3 seeds also have strictly positive clean gain.
- N1–N4 cannot start without an immutable efficacy-ready clean release.
- Historical v1 results are diagnostic and are never edited or combined with clean-v2.
- Provider calls occur only in Tasks 11–12 after all provider-free verification passes.

---

### Task 1: Archive v1 and consolidate implementation onto `main`

**Files:**
- Create: `docs/reports/2026-08-14-clean-v1-diagnostic-archive.md`
- Create: `releases/diagnostic/clean-v1-pilot/manifest.json`
- Merge: `feature/rsebench-pilot`
- Merge: `fix/clean-qualification-baselines`
- Verify: `.gitignore`

**Interfaces:**
- Consumes: immutable local matrix status at `outputs/runs/clean-qualification-20260813/matrix_status.json`, feature commit `6fb608c`, repair commit `3795c23`.
- Produces: canonical `main` containing all implementation and repairs while the diagnostic manifest records old local artifact hashes without tracking the large output tree.

- [ ] **Step 1: Write the diagnostic archive manifest generator test**

  Create `tests/experiments/test_diagnostic_archive.py` after the feature merge and assert a helper called `build_diagnostic_manifest(run_root, git_head)` returns:

  ```python
  assert payload["track"] == "diagnostic"
  assert payload["qualification_version"] == "clean-qualification-v1"
  assert payload["git_head"] == "6fb608c14fb601cdf1c8a34421b6f114110740f6"
  assert payload["run_root_hash"] == sha256_tree(run_root)
  assert payload["formal_qualification"] is False
  ```

- [ ] **Step 2: Merge the implementation lineage without touching untracked data**

  Run from the root checkout:

  ```bash
  git merge --no-ff feature/rsebench-pilot -m "merge: consolidate rsebench pilot implementation"
  git merge --no-ff fix/clean-qualification-baselines -m "merge: consolidate clean baseline repairs"
  ```

  Expected: tracked code appears on `main`; `.env`, `data/`, `methods/`, and `outputs/` remain untracked or ignored and are not staged.

- [ ] **Step 3: Implement the diagnostic manifest helper**

  Create `src/rsebench/experiments/archive.py`:

  ```python
  from pathlib import Path
  from typing import Any

  from rsebench.hashing import sha256_tree


  def build_diagnostic_manifest(run_root: Path, git_head: str) -> dict[str, Any]:
      return {
          "schema_version": "rsebench.diagnostic-release.v1",
          "track": "diagnostic",
          "qualification_version": "clean-qualification-v1",
          "git_head": git_head,
          "run_root": str(run_root.resolve()),
          "run_root_hash": sha256_tree(run_root),
          "formal_qualification": False,
      }
  ```

- [ ] **Step 4: Persist the diagnostic archive and report**

  Generate the compact manifest from the existing run root. The report must list Spreadsheet `+0.0667/+0.1333/0`, OfficeQA `0/3` updates, WebShop two invalid positive signals plus one crash, SkillLearn organize `0/3` positive gains, and billed token total `40,224,114`.

- [ ] **Step 5: Run archive tests and commit**

  ```bash
  PYTHONPATH="$PWD/src" pytest tests/experiments/test_diagnostic_archive.py -q
  git add src/rsebench/experiments/archive.py tests/experiments/test_diagnostic_archive.py \
    docs/reports/2026-08-14-clean-v1-diagnostic-archive.md \
    releases/diagnostic/clean-v1-pilot/manifest.json
  git commit -m "docs: archive clean v1 diagnostic pilot"
  ```

### Task 2: Define ordered baseline patch series and fingerprints

**Files:**
- Create: `patches/baselines/skillopt/series.yaml`
- Create: `patches/baselines/skilladaptor/series.yaml`
- Create: `patches/baselines/skilllearn_self_feedback/series.yaml`
- Move: existing baseline patch files into the corresponding directories
- Create: `src/rsebench/experiments/bootstrap.py`
- Create: `tests/experiments/test_baseline_bootstrap.py`

**Interfaces:**
- Consumes: `benchmark/registry/methods.yaml`, ordered patch files, gitignored `methods/external/`.
- Produces: `BaselineFingerprint`, `load_patch_series(...)`, `verify_baseline(...)`, and a deterministic patchset hash.

- [ ] **Step 1: Write failing fingerprint tests**

  Test that patch order changes the fingerprint and that a patch byte change is detected:

  ```python
  first = build_baseline_fingerprint(
      name="skillopt", repository="https://github.com/microsoft/SkillOpt.git",
      revision="4" * 40, patch_paths=[a, b], python_version="3.13.5",
  )
  second = build_baseline_fingerprint(
      name="skillopt", repository="https://github.com/microsoft/SkillOpt.git",
      revision="4" * 40, patch_paths=[b, a], python_version="3.13.5",
  )
  assert first.patchset_hash != second.patchset_hash
  assert first.fingerprint != second.fingerprint
  ```

- [ ] **Step 2: Implement strict patch-series contracts**

  Add:

  ```python
  class PatchEntry(StrictModel):
      path: str = Field(min_length=1)
      sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
      purpose: Literal["provider", "evidence", "compatibility", "robustness"]


  class PatchSeries(StrictModel):
      baseline: str = Field(min_length=1)
      upstream_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
      patches: list[PatchEntry]
  ```

  Canonicalize the ordered patch identity with compact sorted-key JSON and hash it with SHA-256.

- [ ] **Step 3: Implement read-only baseline verification**

  `verify_baseline(method_root, series)` must verify origin URL/revision externally supplied by registry, `git rev-parse HEAD`, every patch file hash, every `git apply --reverse --check`, and reject unregistered `git diff` changes. It returns a `BaselineFingerprint` and never resets or deletes a checkout.

- [ ] **Step 4: Write series YAML with current patch order**

  Preserve the order currently documented in `patches/baselines/README.md`. Recompute SHA-256 after moving files and update all launchers to resolve patch locations through the series rather than hard-coded flat filenames.

- [ ] **Step 5: Verify all patch replays and commit**

  ```bash
  PYTHONPATH="$PWD/src" pytest tests/experiments/test_baseline_bootstrap.py tests/test_download_scripts.py -q
  rsebench baselines verify
  git add patches/baselines benchmark/registry/methods.yaml \
    src/rsebench/experiments/bootstrap.py tests/experiments/test_baseline_bootstrap.py
  git commit -m "feat: fingerprint replayable baseline patches"
  ```

### Task 3: Add deterministic experiment identity contracts

**Files:**
- Create: `src/rsebench/experiments/__init__.py`
- Create: `src/rsebench/experiments/contracts.py`
- Create: `tests/experiments/test_contracts.py`

**Interfaces:**
- Consumes: `BaselineFingerprint`, repository commit, manifest/data/seed hashes, model/runtime configuration, benchmark/stage/seed.
- Produces: `ExperimentIdentityInput`, `ExperimentIdentity`, `AttemptIdentity`, and `build_experiment_identity(...)`.

- [ ] **Step 1: Write deterministic identity tests**

  Assert dictionary key order does not change `experiment_id`, while method seed, patchset hash, or manifest hash does. Require 64 lowercase hex characters.

- [ ] **Step 2: Implement identity models**

  ```python
  class ExperimentIdentityInput(StrictModel):
      repository_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
      baseline: BaselineFingerprint
      environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
      manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
      dataset_hashes: dict[str, str]
      seed_skill_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
      model: str = Field(min_length=1)
      provider: str = Field(min_length=1)
      runtime: dict[str, Any]
      benchmark: str = Field(min_length=1)
      stage: Literal["clean", "N1", "N2", "N3", "N4"]
      method_seed: int


  class ExperimentIdentity(StrictModel):
      experiment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
      inputs: ExperimentIdentityInput
  ```

- [ ] **Step 3: Add attempt identity**

  `AttemptIdentity` contains `experiment_id`, an opaque UUID4 `attempt_id`, and an integer `attempt_number >= 1`. Retrying preserves the experiment ID and increments the attempt number.

- [ ] **Step 4: Test and commit**

  ```bash
  PYTHONPATH="$PWD/src" pytest tests/experiments/test_contracts.py -q
  git add src/rsebench/experiments tests/experiments/test_contracts.py
  git commit -m "feat: define immutable experiment identities"
  ```

### Task 4: Implement run, stage, and task timing

**Files:**
- Create: `src/rsebench/experiments/timing.py`
- Create: `tests/experiments/test_timing.py`

**Interfaces:**
- Produces: `TimingSpan`, `TimingSummary`, and `TimingRecorder.span(level, name, task_id=None)`.
- Consumed by: common runners, adapters, scheduler, and release summaries.

- [ ] **Step 1: Write deterministic clock tests**

  Inject UTC and monotonic callables. For a span starting at monotonic `10.0` and ending at `12.5`, assert `duration_seconds == 2.5`, timezone-aware start/end timestamps, and status `completed`. Raise inside a second span and assert status `failed` plus `error_type`.

- [ ] **Step 2: Implement timing contracts**

  ```python
  class TimingSpan(StrictModel):
      level: Literal["run", "stage", "task"]
      name: str = Field(min_length=1)
      task_id: str | None = None
      started_at: datetime
      ended_at: datetime
      duration_seconds: float = Field(ge=0.0)
      status: Literal["completed", "failed", "interrupted"]
      error_type: str | None = None


  class TimingSummary(StrictModel):
      run: TimingSpan
      stages: list[TimingSpan]
      tasks: list[TimingSpan]
  ```

  Validate timezone-aware timestamps and require `task_id` exactly when `level == "task"`.

- [ ] **Step 3: Implement append-only timing events**

  `TimingRecorder` writes each completed span as one JSON line to `timing/events.jsonl`, flushes immediately, and creates `timing/summary.json` deterministically. Use `datetime.now(timezone.utc)` for timestamps and `time.monotonic()` for duration.

- [ ] **Step 4: Test and commit**

  ```bash
  PYTHONPATH="$PWD/src" pytest tests/experiments/test_timing.py -q
  git add src/rsebench/experiments/timing.py tests/experiments/test_timing.py
  git commit -m "feat: record hierarchical experiment timing"
  ```

### Task 5: Integrate identity and timing into clean execution

**Files:**
- Modify: `src/rsebench/evolution/clean_contracts.py`
- Modify: `src/rsebench/evolution/clean_runner.py`
- Modify: `src/rsebench/evolution/runner.py`
- Modify: `src/rsebench/evolution/skillopt_executor.py`
- Modify: `src/rsebench/evolution/skilladaptor_executor.py`
- Modify: `src/rsebench/evolution/skilllearn_executor.py`
- Modify: `tests/evolution/test_clean_runner.py`

**Interfaces:**
- Consumes: `ExperimentIdentity`, `AttemptIdentity`, `TimingRecorder`.
- Produces: v2 `CleanEvolutionResult` with `identity`, `timing`, typed execution failures, and task timing emitted by executors.

- [ ] **Step 1: Extend failing clean-runner assertions**

  Require:

  ```python
  assert result.identity.experiment_id == expected_identity.experiment_id
  assert result.timing.run.level == "run"
  assert {span.name for span in result.timing.stages} == {
      "seed_evaluation", "evolution", "clean_test_evaluation"
  }
  assert {span.task_id for span in result.timing.tasks} == {"test"}
  ```

- [ ] **Step 2: Extend the result contract**

  Add required `identity: ExperimentIdentity`, `attempt: AttemptIdentity`, and `timing: TimingSummary` fields. Rename no existing score/artifact fields in this task to preserve adapter compatibility.

- [ ] **Step 3: Wrap common clean stages**

  In `CleanEvolutionRunner.run`, create the run span before seed evaluation; wrap seed evaluation, evolution, and clean-test evaluation in stage spans; always finalize timing and token summaries in `finally`. Failure results include completed timing evidence before raising `CleanQualificationRunError`.

- [ ] **Step 4: Add executor task timing hook**

  Add optional `configure_timing(recorder)` to executors. Each task/episode invocation uses:

  ```python
  with recorder.span(level="task", name=stage, task_id=task.task_id):
      outcome = execute_task(task)
  ```

  Reused evaluations emit a zero-call task span with metadata `reused_from_stage`, not a fabricated provider duration.

- [ ] **Step 5: Run all executor/runner tests and commit**

  ```bash
  PYTHONPATH="$PWD/src" pytest tests/evolution/test_clean_runner.py \
    tests/evolution/test_skillopt_executor.py \
    tests/evolution/test_skilladaptor_executor.py \
    tests/evolution/test_skilllearn_executor.py -q
  git add src/rsebench/evolution tests/evolution
  git commit -m "feat: attach identity and timing to clean runs"
  ```

### Task 6: Implement two-level qualification aggregation

**Files:**
- Create: `src/rsebench/experiments/qualification.py`
- Modify: `scripts/aggregate_clean_qualification.py`
- Modify: `tests/validation/test_aggregate_clean_qualification.py`
- Create: `tests/experiments/test_qualification.py`

**Interfaces:**
- Produces: `SeedReadiness`, `CellReadiness`, `aggregate_cell_readiness(results)`.
- Consumes: three same-identity-family clean results; method seed is the only permitted identity difference.

- [ ] **Step 1: Write readiness tests**

  Cover: 2 engineering-valid + 2 positive => both true; 3 engineering-valid + 0 positive => engineering true/efficacy false; mixed config hashes => error; missing seed => fixed-denominator false.

- [ ] **Step 2: Implement readiness models**

  ```python
  class CellReadiness(StrictModel):
      expected_seeds: list[int]
      engineering_valid_seeds: list[int]
      positive_gain_seeds: list[int]
      engineering_ready: bool
      efficacy_ready: bool
      failure_reasons: list[str]
  ```

  `efficacy_ready` is exactly `engineering_ready and len(positive_gain_seeds) >= 2`.

- [ ] **Step 3: Update aggregate schema**

  Preserve per-seed score/update/failure details, replace ambiguous cell-level `qualified` with explicit readiness fields, and keep a compatibility field only if documented as deprecated.

- [ ] **Step 4: Test and commit**

  ```bash
  PYTHONPATH="$PWD/src" pytest tests/experiments/test_qualification.py \
    tests/validation/test_aggregate_clean_qualification.py -q
  git add src/rsebench/experiments/qualification.py \
    scripts/aggregate_clean_qualification.py \
    tests/experiments/test_qualification.py \
    tests/validation/test_aggregate_clean_qualification.py
  git commit -m "feat: separate clean engineering and efficacy readiness"
  ```

### Task 7: Replace the sequential matrix with an isolated scheduler

**Files:**
- Create: `src/rsebench/experiments/scheduler.py`
- Create: `tests/experiments/test_scheduler.py`
- Modify: `scripts/run_clean_qualification_matrix.py`
- Modify: `tests/validation/test_run_clean_qualification_matrix.py`

**Interfaces:**
- Consumes: expanded units with `experiment_id`, command, `mutable_resource_keys`, and adapter `max_parallel`.
- Produces: atomic `matrix_status.json`, append-only `events.jsonl`, isolated attempt directories, and per-unit queue/run timing.

- [ ] **Step 1: Write concurrency and failure-isolation tests**

  Use four fake units: Spreadsheet/SkillOpt and OfficeQA/SkillOpt share read-only source but no mutable key and must overlap; two units sharing `docker:skilllearn-family` must not overlap; one failure must not cancel unrelated units.

- [ ] **Step 2: Define scheduler contracts**

  ```python
  class ScheduledUnit(StrictModel):
      key: str
      experiment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
      command: list[str]
      output_dir: str
      mutable_resource_keys: list[str] = Field(default_factory=list)
      adapter_key: str
      adapter_max_parallel: int = Field(default=1, ge=1)


  class UnitState(str, Enum):
      pending = "pending"
      queued = "queued"
      running = "running"
      completed = "completed"
      failed = "failed"
      interrupted = "interrupted"
      invalid = "invalid"
  ```

- [ ] **Step 3: Implement bounded parallel execution**

  Use `concurrent.futures.ThreadPoolExecutor` only to manage subprocesses. Acquire sorted mutable-resource locks and adapter semaphores before launch. Set per-unit `TMPDIR`, `XDG_CACHE_HOME`, `HF_HOME`, output root, token ledger, and `PYTHONPATH` to `str(PROJECT_ROOT / "src")`.

- [ ] **Step 4: Implement resume semantics**

  Skip only `completed` with the exact `experiment_id` and an existing result whose identity matches. Every retry gets a new `attempt_id` directory. On `KeyboardInterrupt` or SIGTERM, terminate child processes, stop registered SkillLearn containers, write `interrupted`, and leave prior attempts intact.

- [ ] **Step 5: Test and commit**

  ```bash
  PYTHONPATH="$PWD/src" pytest tests/experiments/test_scheduler.py \
    tests/validation/test_run_clean_qualification_matrix.py -q
  git add src/rsebench/experiments/scheduler.py \
    scripts/run_clean_qualification_matrix.py \
    tests/experiments/test_scheduler.py \
    tests/validation/test_run_clean_qualification_matrix.py
  git commit -m "feat: schedule isolated clean units in parallel"
  ```

### Task 8: Add unified CLI and provider-free preflight

**Files:**
- Modify: `src/rsebench/cli.py`
- Create: `src/rsebench/experiments/preflight.py`
- Create: `tests/experiments/test_cli.py`
- Create: `configs/experiments/clean-v2.yaml`

**Interfaces:**
- Produces: `rsebench baselines bootstrap|verify` and `rsebench experiment preflight|run|status|aggregate`.
- Consumes: patch series, clean-v2 matrix, scheduler, and result aggregator.

- [ ] **Step 1: Write Typer CLI tests**

  Use `CliRunner` and assert preflight prints `provider_calls=0`, all expected unit identities, and refuses `experiment run` without `--confirm-provider-cost`.

- [ ] **Step 2: Add Typer sub-apps**

  Register:

  ```python
  baselines_app = typer.Typer(no_args_is_help=True)
  experiment_app = typer.Typer(no_args_is_help=True)
  app.add_typer(baselines_app, name="baselines")
  app.add_typer(experiment_app, name="experiment")
  ```

  `experiment run` requires `--confirm-provider-cost` and accepts `--max-parallel`.

- [ ] **Step 3: Implement preflight**

  Preflight validates clean worktree commit, local package source, baseline fingerprints, task counts/order, seed hashes, output isolation, commands, timing hooks, mutable resource keys, provider configuration presence without reading key values, and emits no model call.

- [ ] **Step 4: Write clean-v2 matrix**

  Include three fixed seeds and four cells. Spreadsheet/OfficeQA share the read-only SkillOpt source and no mutable key; WebShop uses SkillAdaptor; SkillLearn units declare unique Docker/container resources. Reference only `benchmark/validation/clean_qualification_v2/` manifests.

- [ ] **Step 5: Test and commit**

  ```bash
  PYTHONPATH="$PWD/src" pytest tests/experiments/test_cli.py -q
  PYTHONPATH="$PWD/src" rsebench experiment preflight \
    --matrix configs/experiments/clean-v2.yaml
  git add src/rsebench/cli.py src/rsebench/experiments/preflight.py \
    tests/experiments/test_cli.py configs/experiments/clean-v2.yaml
  git commit -m "feat: expose unified experiment control CLI"
  ```

### Task 9: Implement immutable compact releases

**Files:**
- Create: `src/rsebench/experiments/release.py`
- Create: `tests/experiments/test_release.py`
- Modify: `src/rsebench/cli.py`

**Interfaces:**
- Consumes: aggregate, timing/token summaries, baseline fingerprints, source run hashes.
- Produces: a content-addressed directory below `releases/` containing `manifest.json`, `qualification.json`, `aggregate.json`, `timing-summary.json`, `token-summary.json`, and `report.md`.

- [ ] **Step 1: Write deterministic release tests**

  Freeze the same fixture twice and assert byte-identical content/release ID. Change one patch hash and assert a different ID. Insert a fake `sk-secret` and assert release creation fails before writing.

- [ ] **Step 2: Implement release manifest and readiness barrier**

  `freeze_clean_release(...)` requires every configured cell to be `efficacy_ready`, every source result hash to resolve, and all three seeds per cell. It writes via temporary files followed by atomic rename.

- [ ] **Step 3: Implement secret scanning**

  Reject known credential environment names and token-like patterns in all compact artifacts. Never embed `.env`, raw prompts, stdout, stderr, or trajectories.

- [ ] **Step 4: Add `rsebench release freeze` and commit**

  ```bash
  PYTHONPATH="$PWD/src" pytest tests/experiments/test_release.py -q
  git add src/rsebench/experiments/release.py tests/experiments/test_release.py src/rsebench/cli.py
  git commit -m "feat: freeze compact clean releases"
  ```

### Task 10: Finalize clean-v2 manifests and full provider-free verification

**Files:**
- Modify: `scripts/run_clean_skillopt.py`
- Modify: `scripts/run_clean_skilladaptor.py`
- Modify: `scripts/run_clean_skilllearn.py`
- Create: `benchmark/validation/clean_qualification_v2/skilllearnbench/*.json`
- Create: `benchmark/validation/clean_qualification_v2/skilllearn_manifest.json`
- Create: `benchmark/validation/clean_qualification_v2/webshop_validation_retrieval_evidence.jsonl`
- Modify: v2 OfficeQA/WebShop builders and tests
- Create: `docs/reports/2026-08-14-skilllearn-v2-offline-audit.md`

**Interfaces:**
- Produces: complete portable clean-v2 matrix with no absolute home paths and a provider-free preflight that passes from canonical `main`.

- [ ] **Step 1: Fix launcher provenance and import isolation**

  Every launcher prepends `PROJECT_ROOT/src`, derives `qualification_version` from manifest metadata, and records the v2 identity. OfficeQA dry-run must contain `evaluation.gate_metric=hard`.

- [ ] **Step 2: Version WebShop calibration evidence**

  Commit only the ten retrieval/prompt-injection events for the five frozen validation IDs, record the file SHA-256, and remove runtime dependence on old untracked `outputs/preflight` paths.

- [ ] **Step 3: Run the SkillLearn offline audit**

  Verify instance startup, official verifier completion, seed-skill prompt injection, visible acquisition feedback, validation isolation, accepted skill semantic diffs, and seed-floor/failure categories without calling a model. Use calibration evidence disjoint from the v2 final test when selecting a non-floor canary family.

- [ ] **Step 4: Build SkillLearn v2 manifests**

  Freeze every selected family, exact instance order, train/validation/test partition, image hash, verifier identity, and v2 exclusion/amendment reasons. Do not select final-test instances using observed v1 final-test scores.

- [ ] **Step 5: Run all provider-free verification**

  ```bash
  PYTHONPATH="$PWD/src" pytest -q
  PYTHONPATH="$PWD/src" rsebench baselines verify
  PYTHONPATH="$PWD/src" rsebench experiment preflight \
    --matrix configs/experiments/clean-v2.yaml
  git diff --check
  ```

  Expected: full suite passes; baseline and preflight commands succeed; preflight reports zero provider calls; no `/home/` path exists in committed manifests.

- [ ] **Step 6: Commit clean-v2 readiness**

  ```bash
  git add scripts benchmark/validation/clean_qualification_v2 \
    docs/reports/2026-08-14-skilllearn-v2-offline-audit.md tests
  git commit -m "feat: freeze portable clean v2 qualification"
  ```

### Task 11: Run four failure-targeted clean-v2 canaries

**Files:**
- Create locally: `outputs/runs/clean-v2-canary-20260814/`
- Commit after success: `releases/diagnostic/clean-v2-canaries/...`

**Interfaces:**
- Consumes: provider-free verified canonical commit.
- Produces: one valid canary per cell and a compact diagnostic summary; no canary is promoted if code/config changes afterward.

- [ ] **Step 1: Freeze the canonical commit and preflight one final time**

  Require clean tracked worktree, record HEAD, verify baselines, and save preflight output under the local run root.

- [ ] **Step 2: Run canaries with bounded concurrency**

  Run Spreadsheet regression seed, OfficeQA seed `20260813`, WebShop seed `20260815`, and the preregistered SkillLearn v2 canary through:

  ```bash
  rsebench experiment run --matrix configs/experiments/clean-v2-canary.yaml \
    --max-parallel 4 --confirm-provider-cost
  ```

- [ ] **Step 3: Apply cell-specific canary gates**

  Require identity/timing/usage completeness, 100% task coverage, no systemic failure, artifact update, and accepted update. OfficeQA must use `hard`; WebShop must survive ID/action/Linker paths; SkillLearn must complete container cleanup. A code/config repair invalidates the affected canary and requires a new experiment identity.

- [ ] **Step 4: Commit only compact diagnostic summaries**

  Do not commit raw outputs. Record run IDs, hashes, timing/token totals, scores, and failures in the diagnostic release.

### Task 12: Run and freeze the formal clean-v2 release

**Files:**
- Create locally: `outputs/runs/clean-v2-20260814/`
- Commit: the content-addressed directory created below `releases/clean-v2/`
- Create: `docs/reports/2026-08-14-clean-v2-qualification.md`

**Interfaces:**
- Consumes: unchanged canary-verified commit, baselines, manifests, seeds, model/runtime configuration.
- Produces: three formal seeds per cell, two-level readiness, timing/token aggregates, and an immutable release that either unlocks or blocks N1–N4.

- [ ] **Step 1: Run all fixed clean-v2 units**

  ```bash
  rsebench experiment run --matrix configs/experiments/clean-v2.yaml \
    --max-parallel 4 --confirm-provider-cost
  ```

- [ ] **Step 2: Aggregate without replacing failures**

  Run status and aggregate commands. Every expected seed remains in the denominator; interrupted/failed/invalid attempts remain visible and cannot be replaced by a different seed.

- [ ] **Step 3: Apply two-level readiness**

  Report each cell's engineering-valid seeds and positive-gain seeds. Do not launch N1–N4 unless all four cells are `efficacy_ready`.

- [ ] **Step 4: Freeze and verify the clean release**

  ```bash
  rsebench release freeze --run-id clean-v2-20260814
  PYTHONPATH="$PWD/src" pytest -q
  rg -n 'sk-[A-Za-z0-9_-]+' releases docs/reports/2026-08-14-clean-v2-qualification.md
  ```

  Expected: deterministic release files, full tests pass, and secret scan has no matches.

- [ ] **Step 5: Commit the compact release and report**

  ```bash
  git add releases/clean-v2 docs/reports/2026-08-14-clean-v2-qualification.md
  git commit -m "results: freeze clean v2 baseline qualification"
  ```

  Only after this commit may `configs/experiments/n1.yaml` through `n4.yaml` reference the generated `clean_release_id`.
