# SkillFlow Clean Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `SkillFlow-Task / SkillFlow iterative shared-skill evolution` a reproducible fourth clean-validation domain, screen candidate families with paired base/evolution runs, and freeze only families that satisfy the approved three-replicate efficacy gate.

**Architecture:** Keep SkillFlow's native Harbor runners as the execution engine and capture all required compatibility changes as a replayable patch series against the pinned upstream commit. Add a small RSEBench `skillflow` package for immutable family manifests, typed Harbor-result aggregation, qualification decisions, and a single CLI that owns preflight, screen, confirm, aggregate, and freeze without changing the native task order or patch algorithm.

**Tech Stack:** Python 3.13, Pydantic 2, pytest, PyYAML, Harbor, Docker, DeepSeek OpenAI-compatible API, append-only RSEBench token ledger, Git patch series.

## Global Constraints

- Use SkillFlow upstream commit `7b49ff5a7e26cd7706e959bfa0dba4746d18440d` and record every compatibility/observability change in a hash-pinned patch series.
- `base` and `clean_evolution` start from separate empty shared-skill directories and differ only in cross-task skill patch generation/application.
- Keep the official `ALL_TASK_DIFFICULTY_RANKING.json` order; tasks inside an iterative family are serial.
- Use `replicate_id` values `r1`, `r2`, and `r3`; do not claim deterministic provider seeds.
- Screen Batch A first, add Batch B only when fewer than two preliminary-positive families exist, and stop clean selection after two families formally qualify.
- A family qualifies only when at least two replicates have `delta_late > 0`, the remaining replicate has `delta_late >= 0`, pooled `delta_full > 0`, all paired arms are valid, all evolution replicates patch, and at least two evolution replicates use a stored skill.
- Preserve every valid zero-update, tie, negative-gain, failure, and typed-invalid result.
- Record UTC experiment, family-replicate-arm, and task timing plus agent/verifier/patch durations and 100% observable provider-call token usage.
- Do not run SkillFlow N1–N4, do not continue the five pending SkillLearn Self Feedback families, and do not use clean final skills to initialize later noisy runs.
- Formal provider-backed commands require an explicit `--confirm-provider-cost`; offline tests, manifest builds, dry runs, image builds, and preflight make zero provider calls.
- Work in the current clean main checkout; do not create another experiment worktree.

---

### Task 1: Freeze the existing SkillFlow provider adapter as a replayable baseline

**Files:**
- Create: `patches/baselines/skillflow/skillflow-deepseek-provider.patch`
- Create: `patches/baselines/skillflow/series.yaml`
- Remove: `patches/baselines/skillflow-deepseek-api.patch`
- Modify: `benchmark/registry/methods.yaml`
- Modify: `patches/baselines/README.md`
- Test: `tests/experiments/test_baseline_bootstrap.py`
- Test: `tests/adapters/test_native_baselines.py`

**Interfaces:**
- Consumes: current DeepSeek-compatible changes in `methods/external/skillflow` and upstream revision `7b49ff5...`.
- Produces: `load_patch_series("patches/baselines/skillflow/series.yaml")` and a `verify_baseline(...)` fingerprint for method key `skillflow`.

- [ ] **Step 1: Write the failing patch-series tests**

Add a registry test that loads `methods.yaml`, requires `methods.skillflow.patch_series`, loads the series, and asserts the ordered purposes begin with `provider`. Add a replay test that applies the registered patch to a temporary archive of the upstream target paths and asserts these files exist:

```python
assert series.baseline == "skillflow"
assert series.upstream_revision == "7b49ff5a7e26cd7706e959bfa0dba4746d18440d"
assert series.patches[0].purpose == "provider"
assert "libs/harbor_noinstall_agents/deepseek_api.py" in patch_text
```

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src uv run --no-sync pytest -q \
  tests/experiments/test_baseline_bootstrap.py \
  tests/adapters/test_native_baselines.py -k skillflow
```

Expected: fail because `skillflow` has no registered `series.yaml`.

- [ ] **Step 3: Create the canonical provider patch and series**

Copy only source-controlled provider/compatibility changes from the external checkout into `skillflow-deepseek-provider.patch`: the DeepSeek Harbor agent, disabled-thinking request body, compatible `ExecInput`, pinned Harbor revision, and the external adapter test. Do not include `.rsebench`, `__pycache__`, `.pytest_cache`, job outputs, credentials, or local virtual environments. Hash the final patch with `sha256_file(...)` and serialize the returned digest into `sha256`:

```python
series_payload = {
    "baseline": "skillflow",
    "upstream_revision": "7b49ff5a7e26cd7706e959bfa0dba4746d18440d",
    "patches": [{
        "path": "skillflow-deepseek-provider.patch",
        "sha256": sha256_file(provider_patch),
        "purpose": "provider",
    }],
}
```

Register `patch_series: patches/baselines/skillflow/series.yaml` and document the apply order.

- [ ] **Step 4: Verify GREEN and commit**

Run the focused tests, `git diff --check`, and `verify_baseline` against a clean temporary reconstruction. Commit:

```bash
git commit -m "build: freeze skillflow provider adapter"
```

### Task 2: Add immutable SkillFlow family-manifest contracts

**Files:**
- Create: `src/rsebench/skillflow/__init__.py`
- Create: `src/rsebench/skillflow/contracts.py`
- Create: `src/rsebench/skillflow/manifest.py`
- Create: `scripts/build_skillflow_clean_manifest.py`
- Create: `configs/experiments/skillflow-clean-qualification-v1.yaml`
- Generate: `benchmark/validation/skillflow_clean_qualification_v1/input_manifest.json`
- Test: `tests/skillflow/test_contracts.py`
- Test: `tests/skillflow/test_manifest.py`
- Test: `tests/validation/test_build_skillflow_clean_manifest.py`

**Interfaces:**
- Consumes: `data/raw/skillflow_tasks/test_tasks/{family}/ALL_TASK_DIFFICULTY_RANKING.json` and valid Harbor task directories.
- Produces: `SkillFlowInputManifest`, `SkillFlowFamilyManifest`, `SkillFlowTaskIdentity`, `build_input_manifest(data_root, config)`, and the exact candidate batches/replicates used by later tasks.

- [ ] **Step 1: Write failing contract tests**

Define the desired immutable types through tests:

```python
manifest = SkillFlowInputManifest.model_validate(payload)
assert manifest.schema_version == "rsebench.skillflow-input.v1"
assert manifest.replicates == ["r1", "r2", "r3"]
assert manifest.batch_a == [
    "Document-Fraud-Detection",
    "Operational-Recovery-Planning",
    "HWPX-Document-Automation",
    "SEC-13F-Financial-Analysis",
]
assert manifest.batch_b == [
    "OCR-Data-Extraction",
    "Cross-Format-Data-Reconciliation",
]
assert [task.order for task in manifest.families[0].tasks] == list(range(1, 9))
invalid_payload = manifest.model_dump(mode="json")
invalid_payload["replicates"] = ["r1", "r1", "r3"]
with pytest.raises(ValidationError):
    SkillFlowInputManifest.model_validate(invalid_payload)
```

Test that an unknown ranking entry, unranked valid task, duplicate task, path escape, missing `task.toml`, or hash drift fails closed.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src uv run --no-sync pytest -q \
  tests/skillflow/test_contracts.py \
  tests/skillflow/test_manifest.py \
  tests/validation/test_build_skillflow_clean_manifest.py
```

Expected: import failure because `rsebench.skillflow` does not exist.

- [ ] **Step 3: Implement the minimal manifest builder**

Implement frozen Pydantic models with these core fields:

```python
class SkillFlowTaskIdentity(FrozenStrictModel):
    task_id: str
    order: int = Field(ge=1)
    relative_path: str
    task_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

class SkillFlowFamilyManifest(FrozenStrictModel):
    family: str
    ranking_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tasks: list[SkillFlowTaskIdentity]

class SkillFlowInputManifest(FrozenStrictModel):
    schema_version: Literal["rsebench.skillflow-input.v1"]
    benchmark: Literal["skillflow_tasks"]
    baseline: Literal["skillflow"]
    upstream_revision: str
    qualification_contract: Literal["skillflow-clean-qualification-v1"]
    batch_a: list[str]
    batch_b: list[str]
    replicates: list[Literal["r1", "r2", "r3"]]
    families: list[SkillFlowFamilyManifest]
```

Hash each complete task tree with `sha256_tree`, preserve ranking order, and write canonical JSON atomically. The YAML contains no credentials and fixes model, turns, max tokens, timeouts, Docker image name, candidate batches, and the qualification gate.

- [ ] **Step 4: Verify GREEN, generate, and commit**

Run focused tests, generate the manifest twice, and assert byte identity and `provider_calls=0`. Commit:

```bash
git commit -m "feat: freeze skillflow clean candidates"
```

### Task 3: Parse Harbor evidence and implement the fixed qualification gate

**Files:**
- Create: `src/rsebench/skillflow/results.py`
- Create: `src/rsebench/skillflow/qualification.py`
- Test: `tests/skillflow/test_results.py`
- Test: `tests/skillflow/test_qualification.py`

**Interfaces:**
- Consumes: native Harbor `result.json`, per-trial `result.json`, ATIF `agent/trajectory.json`, `skill_patch_history.jsonl`, shared-skill directories, and token/timing files.
- Produces: `parse_arm_result(...) -> SkillFlowArmResult`, `pair_replicate(...) -> SkillFlowReplicateResult`, and `qualify_family(...) -> SkillFlowFamilyDecision`.

- [ ] **Step 1: Write failing parser tests with real-format fixtures**

Construct minimal Harbor directories containing task 1/2 rewards, timestamps, agent/verifier spans, a patch-history row, an ATIF `Skill` tool call, and token events. Assert:

```python
arm = parse_arm_result(job_dir, family_manifest, arm="clean_evolution")
assert arm.complete is True
assert arm.task_rewards == [0.0, 1.0]
assert arm.patch_count == 2
assert arm.nonempty_patch_count == 2
assert arm.skill_used_task_count == 1
assert arm.task_results[1].agent_duration_seconds == 4.0
assert arm.task_results[1].verifier_duration_seconds == 1.0
```

Also test missing task, duplicate task ID, exception, unparseable reward, task checksum mismatch, absent patch history, and invalid token coverage as typed invalid reasons.

- [ ] **Step 2: Verify RED with qualification tests**

Cover the exact gate:

```python
decision = qualify_family([r1_positive, r2_positive, r3_tie])
assert decision.status == "qualified"

assert qualify_family([r1_positive, r2_positive, r3_negative]).status == "not_qualified"
assert qualify_family([r1_positive, r2_tie, r3_tie]).status == "not_qualified"
assert qualify_family([r1_positive, r2_positive, r3_invalid]).status == "incomplete"
```

Run the two modules and confirm RED from missing implementations.

- [ ] **Step 3: Implement minimal evidence normalization**

Use Harbor timestamps for task, agent, and verifier durations; use patch-history timestamps for patch duration; detect skill use only from explicit `Skill` calls or reads under known mounted skill roots; aggregate token shards with the existing RSEBench ledger. Compute:

```python
delta_late = mean(evolution_rewards[1:]) - mean(base_rewards[1:])
delta_full = mean(evolution_rewards) - mean(base_rewards)
qualified = (
    len(positive_late_replicates) >= 2
    and all(item.delta_late >= 0 for item in replicates)
    and pooled_delta_full > 0
    and all(item.evolution.nonempty_patch_count > 0 for item in replicates)
    and sum(item.evolution.skill_used_task_count > 0 for item in replicates) >= 2
)
```

Keep infrastructure invalid separate from valid zero-update/no-use/no-gain outcomes.

- [ ] **Step 4: Verify GREEN and commit**

Run the focused tests and commit:

```bash
git commit -m "feat: qualify skillflow clean evolution"
```

### Task 4: Add the single SkillFlow clean control-plane CLI

**Files:**
- Create: `src/rsebench/skillflow/runner.py`
- Create: `scripts/run_skillflow_clean.py`
- Test: `tests/skillflow/test_runner.py`
- Test: `tests/validation/test_run_skillflow_clean.py`

**Interfaces:**
- Consumes: experiment YAML, input manifest, registered patch series, external SkillFlow checkout, Docker image, and the Task 3 parsers.
- Produces: subcommands `preflight`, `screen`, `confirm`, `aggregate`, and `freeze`; isolated native config files and output directories.

- [ ] **Step 1: Write failing preflight and command-construction tests**

Assert preflight makes zero provider calls and fails on a dirty/unverified patch target, missing Docker image/digest, wrong task hash, nonempty initial skill directory, or output collision. Assert exact commands:

```python
base_command = [python, "family_job_runner.py", "--config", base_yaml,
                "--only-group", family, "--dataset-path", family_path,
                "--run-root-dir", arm_root]
evolution_command = [python, "iterative_shared_skills_runner.py", "--config", evolution_yaml,
                     "--only-group", family, "--dataset-path", family_path,
                     "--run-root-dir", arm_root]
```

Assert provider-backed `screen` and `confirm` reject missing `--confirm-provider-cost`, while `--dry-run` writes a manifest with `provider_calls=0`.

- [ ] **Step 2: Verify RED**

Run the focused tests; expect missing CLI/runner imports.

- [ ] **Step 3: Implement isolated native execution**

Generate per-arm YAML with `DeepSeekAPIAgent`, model `deepseek-v4-flash`, temperature 0, max turns 30, max completion 2048, empty initial shared skills, `copy_task_skills=false`, official task order, and one task at a time for evolution. Wrap subprocess environments with:

```python
env = token_context_environment(
    combined_method_env("skillflow"),
    ledger_dir=run_root / "token_ledger",
    run_id=run_id,
    domain="skill_native",
    benchmark="skillflow_tasks",
    arm=arm,
    stage="worker" if arm == "base" else "worker_and_patcher",
)
```

Use `TimingRecorder` with run/stage/task summaries, persist `run_manifest.json` before execution, never overwrite a different attempt, and make `screen` run only `r1` Batch A. `confirm` accepts only preliminary-positive families and schedules missing `r2/r3` pairs.

- [ ] **Step 4: Implement aggregate and freeze**

`aggregate` writes `aggregate.json` containing every screened family and typed status. `freeze` refuses fewer than two qualified families, verifies all hashes again, copies only machine-readable compact evidence to the validation manifest, and never copies credentials or raw trajectories.

- [ ] **Step 5: Verify GREEN and commit**

Run focused tests, offline fixture/dry-run commands, secret scans, and commit:

```bash
git commit -m "feat: add skillflow clean control plane"
```

### Task 5: Add native patch timing and complete token observability

**Files:**
- Modify through patch: `methods/external/skillflow/iterative_shared_skills_runner.py`
- Modify through patch: `methods/external/skillflow/libs/skill_evolution/patcher.py`
- Modify through patch: `methods/external/skillflow/libs/terminus_agent/llms/lite_llm.py`
- Create: `patches/baselines/skillflow/skillflow-observability.patch`
- Modify: `patches/baselines/skillflow/series.yaml`
- Test: `tests/skillflow/test_patch_observability.py`
- Test: `tests/experiments/test_baseline_bootstrap.py`

**Interfaces:**
- Consumes: existing RSEBench token-context environment and native patch hook.
- Produces: one token event per patcher provider attempt and patch-history fields `started_at`, `ended_at`, `duration_seconds`, `status`, and `error_type`.

- [ ] **Step 1: Write failing observability tests**

Use a fake LiteLLM response with usage and assert `record_token_event` receives prompt/completion tokens, provider/model, and patcher stage. Use a fake monotonic/UTC clock around patch generation and assert a history row is written even when patch generation raises.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src uv run --no-sync pytest -q \
  tests/skillflow/test_patch_observability.py \
  tests/experiments/test_baseline_bootstrap.py -k skillflow
```

Expected: fail because native patch calls do not emit token events or timing.

- [ ] **Step 3: Implement minimal observability without algorithm changes**

After each LiteLLM completion, extract `response.usage` and call:

```python
record_token_event(
    usage=usage,
    cache_hit=False,
    billed=True,
    status="success",
    source="skillflow.litellm",
    provider="deepseek",
    model=self._model_name,
    stage="patcher",
)
```

Record an unobservable error event on failed calls. In the native hook, use timezone-aware UTC and monotonic duration around generate/apply, append failure rows before propagating, and preserve the existing prompt, snapshot, patch acceptance, and application behavior.

- [ ] **Step 4: Verify GREEN and regenerate the two-patch series**

Create an incremental `skillflow-observability.patch`, append it with purpose `evidence`, update hashes, reconstruct both patches on clean upstream, and compare the intended source-file snapshot to the live checkout. Commit:

```bash
git commit -m "feat: record skillflow patch evidence"
```

### Task 6: Migrate the fourth-domain registry and collaborator documentation

**Files:**
- Modify: `benchmark/registry/benchmarks.yaml`
- Modify: `benchmark/registry/methods.yaml`
- Modify: `benchmark/registry/adapters.yaml`
- Modify: `benchmark/registry/splits.yaml`
- Modify: `docs/project-roadmap.md`
- Modify: `docs/reports/current-experiment-status.md`
- Test: `tests/core1/test_registry.py`
- Test: `tests/adapters/test_adapter_registry.py`
- Test: `tests/skillflow/test_registry.py`

**Interfaces:**
- Consumes: the executable control plane and approved design.
- Produces: `skillflow_tasks / skillflow` as the active fourth clean-validation domain and `skilllearnbench / skilllearn_self_feedback` as a retained diagnostic weak baseline.

- [ ] **Step 1: Write failing registry tests**

Assert exactly four main clean-validation domains, with these skill entries:

```python
assert benchmarks["skillflow_tasks"]["active"] is True
assert benchmarks["skillflow_tasks"]["tier"] == "core1"
assert benchmarks["skillflow_tasks"]["primary_method"] == "skillflow"
assert benchmarks["skilllearnbench"]["tier"] == "diagnostic"
assert methods["skillflow"]["active"] is True
assert methods["skillflow"]["code_status"] == "runnable_with_deepseek_adapter"
```

Require a migration note that preserves historical SkillLearn reports and says SkillFlow is not frozen until two families qualify.

- [ ] **Step 2: Verify RED**

Run the three focused registry test modules and confirm the current SkillLearn core definition fails.

- [ ] **Step 3: Update machine-readable and human-readable scope**

Change only project status/ownership metadata. Do not create SkillFlow N1–N4 operators or claim frozen efficacy. Keep all SkillLearn files and operator definitions discoverable under diagnostic/history status.

- [ ] **Step 4: Verify GREEN and commit**

Run registry tests plus roadmap link/status scans and commit:

```bash
git commit -m "docs: make skillflow the fourth clean domain"
```

### Task 7: Build, preflight, smoke, and execute the approved adaptive clean screen

**Files:**
- Generate ignored: `outputs/preflight/skillflow-clean-qualification-v1/`
- Generate ignored: `outputs/runs/skillflow-clean-qualification-v1-20260816/`
- Generate after results: `docs/reports/2026-08-16-skillflow-clean-screen.md`
- Generate only after two families qualify: `benchmark/validation/skillflow_clean_qualification_v1/manifest.json`

**Interfaces:**
- Consumes: Tasks 1–6, the local DeepSeek credential, Docker, 166 frozen tasks, and explicit user authorization to execute.
- Produces: fresh readiness evidence, Batch A r1 paired results, adaptive confirmation runs, and a freeze or typed blocked decision.

- [ ] **Step 1: Run the full provider-free verification gate**

Run all focused tests, then the complete suite:

```bash
PYTHONPATH=src uv run --no-sync pytest -q
```

Run credential, absolute-path, placeholder, patch replay, and `git diff --check` scans. Do not continue on any failure.

- [ ] **Step 2: Build and pin the SkillFlow environment**

Recreate or verify the SkillFlow virtual environment from the patched upstream, record Python/Harbor/LiteLLM versions and lock hash, build `skillflow/harbor-cli-base:ubuntu24.04`, and record its immutable Docker digest. Re-run image inspection without rebuilding and require the same digest.

- [ ] **Step 3: Run offline and online smoke levels**

Run offline fixture transport/structured/tool tests, then real transport, structured, and fake-environment tool smokes. Finally run one bounded native task and a two-task iterative family prefix in fresh output directories. Verify actual verifier execution, one persisted patch, subsequent skill visibility, 100% token observation, and all three timing levels.

- [ ] **Step 4: Re-estimate wall time and cost from fresh smoke evidence**

Write measured task, patch, token, and wall-clock ranges to the preflight report. If the same infrastructure error repeats, stop before Batch A and report it instead of launching more tasks.

- [ ] **Step 5: Run Batch A screening**

Execute exactly one paired `r1` for the four preregistered families with isolated arm outputs. Parallelize families only within verified Docker/API limits; keep each evolution family serial. Monitor terminal state, preserve failures, then run `aggregate` before scheduling anything else.

- [ ] **Step 6: Apply the adaptive rule**

If fewer than two families are preliminary positive, run Batch B `r1` and aggregate again. Confirm only the top two preliminary-positive families by running their missing `r2/r3` pairs. If confirmation yields one qualifier, retain it and screen the next two unscreened families; never lower the gate.

- [ ] **Step 7: Freeze or report blocked status**

When two families qualify, run `freeze`, verify manifest/result/token/timing hashes, and write the Chinese report. If the model cannot produce two qualifiers after all candidates permitted by the adaptive loop, write a typed `clean efficacy blocked` report without N1–N4.

- [ ] **Step 8: Final verification and commit**

Re-run the complete test suite and release-integrity checks, inspect the exact diff, and commit only compact manifests/config/docs/code/tests. Raw Harbor jobs, caches, token shards, Docker artifacts, and credentials remain ignored.
