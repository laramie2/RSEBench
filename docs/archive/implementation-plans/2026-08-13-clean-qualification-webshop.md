# WebShop SkillAdaptor Clean Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair and audit SkillAdaptor's native WebShop execution path, freeze a 5/5/20 clean split, and expose a budget-locked clean qualification launcher without switching baselines.

**Architecture:** The external SkillAdaptor checkout receives an incremental, replayable compatibility patch for lexical retrieval, per-episode retrieval evidence, and typed errors. RSEBench consumes those native audit records through `SkillAdaptorExecutor`, selects five validation goals using only repaired seed calibration, and runs the existing SkillAdaptor orchestrator for at most three 15-step iterations through `CleanEvolutionRunner`.

**Tech Stack:** Python 3.13, pytest, pinned SkillAdaptor checkout, pinned WebShop simulator, DeepSeek V4 Flash, JSONL audit records.

## Global Constraints

- SkillAdaptor remains the WebShop baseline; do not substitute RethinkSkill.
- Formal size is exactly 5 acquisition, 5 validation, and 20 untouched clean-test goals.
- Formal budget is at most 3 SkillAdaptor iterations and 15 actions per episode.
- Native validation `min_sample_size` is exactly 5.
- Lexical threshold calibration uses retrieval coverage only; no clean-test correctness enters calibration.
- Validation selection uses the first two repaired seed successes and first three repaired seed failures in the frozen structural candidate order.
- Every episode persists candidate skill IDs, similarity scores, retrieved IDs, injected IDs, and any exception type/message.
- An episode exception invalidates the run; it is not converted to an ordinary zero.
- Goal `994` must complete without infrastructure/protocol error before formal execution.
- Existing applied SkillAdaptor patches remain intact and the new changes are captured as an incremental replayable patch.

---

### Task 1: Preserve full WebShop episode failures

**Files:**
- Modify external: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilladaptor/skill-adaptor/adapters/webshop_adapter/env_wrapper.py`
- Modify external: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilladaptor/skill-adaptor/adapters/webshop_adapter/evaluator.py`
- Modify: `scripts/eval_skilladaptor_webshop.py`
- Modify: `tests/evolution/test_skilladaptor_executor.py`

**Interfaces:**
- Native episode fields: `error_type`, `error_message`, and `error_stage`.
- Native evaluator metrics: `execution_failures: dict[str, str]` and `task_results: dict[str, dict]`.
- RSEBench evaluation diagnostics preserve the same `execution_failures` mapping.

Before changing the external checkout, create a temporary snapshot with
`mktemp -d` and copy `llm_policy.py`, `env_wrapper.py`, `evaluator.py`,
`core/orchestrator.py`, and the absent/new `core/retrieval_audit.py` path state.
Retain the temporary directory path through Task 4 so the new patch is an
incremental diff over the already applied compatibility patches.

- [ ] **Step 1: Strengthen the existing swallowed-error test**

Change the broken policy to raise `RuntimeError("no Action field for goal 7")`
and assert:

```python
assert episode["error_type"] == "RuntimeError"
assert episode["error_message"] == "no Action field for goal 7"
assert episode["error_stage"] == "policy_or_environment_step"
```

Add an evaluator test with one successful episode and one errored episode:

```python
assert metrics["execution_failures"] == {
    "goal_7": "RuntimeError: no Action field for goal 7"
}
assert metrics["task_results"]["goal_7"]["valid"] is False
assert metrics["sample_size"] == 2
```

Add an eval-script fixture and assert the emitted RSEBench result keeps the
failure mapping under `diagnostics.execution_failures`.

- [ ] **Step 2: Run the focused tests and confirm the message is missing**

```bash
pytest tests/evolution/test_skilladaptor_executor.py -k 'episode_records or evaluator or eval_script' -v
```

Expected: assertions for `error_message` and `execution_failures` fail.

- [ ] **Step 3: Implement typed failure persistence**

In `run_episode`, initialize `error_type`, `error_message`, and `error_stage` to
`None`. In the existing exception handler set:

```python
error_type = type(exc).__name__
error_message = str(exc)
error_stage = "policy_or_environment_step"
```

Copy all three fields into the returned episode when an exception occurs. In
`WebShopEvaluator._compute_metrics`, retain the current score fields and add:

```python
task_results = {
    f"goal_{row['goal_idx']}": {
        "score": float(row["total_reward"]),
        "success": bool(row["success"]),
        "num_steps": int(row["num_steps"]),
        "valid": not bool(row.get("error_type")),
        "error_type": row.get("error_type"),
        "error_message": row.get("error_message"),
    }
    for row in results
}
execution_failures = {
    task_id: f"{row['error_type']}: {row['error_message']}"
    for task_id, row in task_results.items()
    if row["error_type"]
}
```

Update `eval_skilladaptor_webshop.py` to copy the same fields from each episode
and include the non-empty failure mapping in diagnostics. Do not omit errored
task IDs from `per_task_scores`; coverage and validity are separate checks.

- [ ] **Step 4: Run the tests**

```bash
pytest tests/evolution/test_skilladaptor_executor.py -k 'episode_records or evaluator or eval_script' -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Leave the external diff uncommitted until the incremental patch task**

Record the modified external file list with:

```bash
git -C /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilladaptor status --short
```

Expected: the previously applied files plus the two intentional WebShop files
are modified; no generated credential or output file appears.

---

### Task 2: Calibrate lexical retrieval and persist injection evidence

**Files:**
- Modify external: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilladaptor/skill-adaptor/adapters/webshop_adapter/llm_policy.py`
- Create external: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilladaptor/skill-adaptor/core/retrieval_audit.py`
- Modify external: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilladaptor/skill-adaptor/adapters/webshop_adapter/env_wrapper.py`
- Modify external: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilladaptor/skill-adaptor/core/orchestrator.py`
- Modify: `scripts/baselines/common_env.py`
- Modify: `tests/evolution/test_skilladaptor_executor.py`

**Interfaces:**
- Environment: `SkillAdaptor_LEXICAL_SKILL_THRESHOLD=0.10`.
- Environment: `RSEBENCH_SKILL_RETRIEVAL_AUDIT=<absolute JSONL path>`.
- Policy: `begin_episode(task_text: str, episode_id: str | None = None) -> None`.
- Audit event schema: episode ID, threshold, lexical flag, ranked candidates, retrieved IDs, and injected IDs.
- Native report fields: `training_task_ids`, `validation_task_ids`, and `accepted_update_count`.

- [ ] **Step 1: Write failing lexical-policy and audit tests**

Use the released seed skill `webshop_constraint_check` and the three known
validation prompts for goals 1195, 735, and 994. Set lexical matching and the
0.10 threshold. Assert each call to `begin_episode` retrieves the seed:

```python
policy.begin_episode(prompt, episode_id=f"goal_{goal_idx}")
assert [skill.id for skill in policy.skills_for_episode()] == [
    "webshop_constraint_check"
]
```

Build one prompt and assert it contains the seed title. Read the JSONL audit and
assert every event contains numeric candidate scores, the retrieved seed ID,
and `injected_skill_ids=["webshop_constraint_check"]`.

Add a control test proving semantic mode retains threshold 0.35 when the
lexical environment flag is absent. Add an orchestrator report test proving
two accepted skills plus one accepted global-prior update produce
`accepted_update_count=3` and preserve exact training/validation task IDs.

- [ ] **Step 2: Run and confirm the current 0.35 threshold returns no skills**

```bash
pytest tests/evolution/test_skilladaptor_executor.py -k 'lexical_policy or retrieval_audit' -v
```

Expected: the three retrieval assertions fail with an empty skill list.

- [ ] **Step 3: Implement the explicit lexical threshold**

In `scripts/baselines/common_env.py`, add:

```python
"SkillAdaptor_LEXICAL_SKILL_THRESHOLD": "0.10",
```

In the policy constructor, select threshold as follows:

```python
lexical = os.environ.get("SkillAdaptor_LEXICAL_MATCHING", "").strip().lower() in {
    "1", "true", "yes", "on",
}
threshold = (
    float(os.environ.get("SkillAdaptor_LEXICAL_SKILL_THRESHOLD", "0.10"))
    if lexical
    else 0.35
)
self._skill_matcher = SemanticSkillMatcher(
    api_key=embedding_api_key or config.get("embedding_api_key"),
    base_url=embedding_base_url or config.get("embedding_base_url"),
    similarity_threshold=threshold,
)
```

Import `os` explicitly. Do not lower the generic matcher threshold globally;
the change is scoped to WebShop policy retrieval.

- [ ] **Step 4: Implement append-only retrieval events**

`core/retrieval_audit.py` exposes:

```python
def append_retrieval_audit(payload: dict[str, object]) -> None:
    configured = os.environ.get("RSEBENCH_SKILL_RETRIEVAL_AUDIT", "").strip()
    if not configured:
        return
    path = Path(configured).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
```

Change `_retrieve_skills_for_task` to call `rank_skills_for_task`, retain
candidates above `self._skill_matcher.similarity_threshold`, and append a
`retrieval` event. `begin_episode` receives the goal ID supplied by
`env_wrapper`. `_build_prompt` appends a second `prompt_injection` event with
the IDs actually sent to `format_skills_for_llm_prompt`. Both events share the
episode ID; audit readers require exactly one of each per executed episode.

In the orchestrator, store the training and validation task IDs passed to
`run`, initialize `accepted_update_count=0`, add the number of accepted
revised/new skills after each validation result, and add one whenever
`_try_adopt_global_prior` returns true. Persist all three fields in
`SkillAdaptor_report.json`.

- [ ] **Step 5: Run the retrieval tests**

```bash
pytest tests/evolution/test_skilladaptor_executor.py -k 'lexical or retrieval_audit' -v
```

Expected: all selected tests pass without an embedding endpoint.

---

### Task 3: Diagnose and repair goal 994 under the audited path

**Files:**
- Modify only the external file identified by the captured `error_stage` and `error_message`.
- Modify: `tests/evolution/test_skilladaptor_executor.py`
- Create: `outputs/preflight/clean-qualification-v1/webshop/goal_994/result.json`

**Interfaces:**
- Consumes: full failure fields from Task 1 and retrieval evidence from Task 2.
- Produces: one successful, 15-step-bounded seed evaluation for goal 994 with a non-empty retrieval audit.

- [ ] **Step 1: Run one isolated audited reproduction**

```bash
SkillAdaptor_LEXICAL_MATCHING=1 SkillAdaptor_LEXICAL_SKILL_THRESHOLD=0.10 \
RSEBENCH_SKILL_RETRIEVAL_AUDIT=outputs/preflight/clean-qualification-v1/webshop/goal_994/retrieval.jsonl \
/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/webshop/.venv/bin/python \
scripts/eval_skilladaptor_webshop.py \
--method-root /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skilladaptor/skill-adaptor \
--webshop-root /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/webshop \
--manifest outputs/preflight/clean-qualification-v1/webshop/goal_994/manifest.json \
--skills benchmark/core1/seeds/skilladaptor_webshop.json \
--max-episode-steps 15 \
--output outputs/preflight/clean-qualification-v1/webshop/goal_994/result.json
```

The manifest contains `{"input_tasks": [], "validation_tasks": [],
"test_tasks": [994]}`. Expected after Task 1: either the result has no
execution failure or it contains one exact exception class/message and stage.

- [ ] **Step 2: Convert the exact captured failure into a deterministic test**

Use the smallest native boundary that raises the captured exception: policy
parser for response-format errors, `WebShopEnvWrapper.step` for simulator
errors, or evaluator serialization for output errors. The test name includes
`goal_994_regression` and asserts the captured message before the fix.

- [ ] **Step 3: Implement only the evidence-supported repair**

Preserve strict action parsing and WebShop scoring. The allowed contained
recovery for a response-format failure is one additional deterministic model
request with this exact user suffix:

```text
Your previous response did not contain one executable WebShop action. Return
only one line in the form Action: search[...] or Action: click[...].
```

Do not invent a fallback product, action, or reward. For a simulator or
serialization failure, fix the exact invalid native value identified in Step 2
and retain the regression fixture. Any different failure class stops this task
for a design amendment rather than being hidden as zero.

- [ ] **Step 4: Run the regression and isolated reproduction again**

```bash
pytest tests/evolution/test_skilladaptor_executor.py -k goal_994_regression -v
```

Then repeat the Step 1 command. Expected: the test passes;
`diagnostics.execution_failures` is empty; retrieval JSONL contains goal 994
and the seed ID; the episode executes at least two actions or reaches a native
terminal state before that.

---

### Task 4: Capture the complete incremental SkillAdaptor patch

**Files:**
- Create: `patches/baselines/skilladaptor-clean-qualification.patch`
- Modify: `patches/baselines/README.md`

**Interfaces:**
- Applies after `skilladaptor-lexical-fault-dedup.patch`.
- Reproduces Tasks 1-3 from the pinned SkillAdaptor revision without including credentials or outputs.

- [ ] **Step 1: Snapshot the pre-change versions before editing Tasks 1-3**

At execution start, create a temporary directory with `mktemp -d` and copy the
four external files changed by this plan. Record that temporary path in the
task notes. This snapshot is only for producing an incremental diff and is not
committed.

- [ ] **Step 2: Generate a labeled incremental unified diff**

For each changed/new external file, run `diff -u` with labels rooted at
`a/skill-adaptor/FILE` and `b/skill-adaptor/FILE`; concatenate the results in the
stable order `core/retrieval_audit.py`, `llm_policy.py`, `env_wrapper.py`,
`evaluator.py`, followed by the evidence-supported goal-994 file. The resulting
patch must not contain unrelated hunks already represented by the five earlier
SkillAdaptor patches.

- [ ] **Step 3: Verify forward and reverse application in a temporary checkout**

Apply the five patches listed in `patches/baselines/README.md`, then apply the
new patch with `git apply --check` and `git apply`. Verify
`git apply --reverse --check` succeeds for the new patch.

- [ ] **Step 4: Update patch ordering and commit**

Append the new patch after `skilladaptor-lexical-fault-dedup.patch` in the
README, then run:

```bash
git add patches/baselines/skilladaptor-clean-qualification.patch patches/baselines/README.md scripts/baselines/common_env.py scripts/eval_skilladaptor_webshop.py tests/evolution/test_skilladaptor_executor.py
git commit -m "fix: audit SkillAdaptor WebShop execution"
```

---

### Task 5: Expose SkillAdaptor execution audit to the clean runner

**Files:**
- Modify: `src/rsebench/evolution/skilladaptor_executor.py`
- Modify: `tests/evolution/test_skilladaptor_executor.py`

**Interfaces:**
- Produces: `EvolutionArtifact.execution_audit` using native report fields.
- Passes: absolute `RSEBENCH_SKILL_RETRIEVAL_AUDIT` to training and evaluation subprocesses.
- Invalidates: any evaluation whose `diagnostics.execution_failures` is non-empty.

- [ ] **Step 1: Write failing executor-audit tests**

Make the fake native report contain:

```json
{
  "iterations": 2,
  "accepted_update_count": 1,
  "newly_adopted_skill_ids": ["verify-options"],
  "training_task_ids": ["goal_1", "goal_2", "goal_3", "goal_4", "goal_5"],
  "validation_task_ids": ["goal_6", "goal_7", "goal_8", "goal_9", "goal_10"]
}
```

Assert accepted count is 1, both ID lists are preserved, the training command
uses `--max-iterations 3 --max-episode-steps 15`, and the retrieval audit path
is inside the run directory. Add an evaluation failure fixture and assert the
returned `EvaluationResult.diagnostics["execution_failures"]` is non-empty.

- [ ] **Step 2: Run the focused executor test and verify failure**

```bash
pytest tests/evolution/test_skilladaptor_executor.py -k executor_runs_native -v
```

Expected: the execution audit assertion fails.

- [ ] **Step 3: Parse the native report into `EvolutionExecutionAudit`**

Require all report fields shown in Step 1. Use the native accepted count
directly; copy iterations, final skill count, and adopted IDs into audit
metadata. Set separate audit paths for seed, clean evolution, and clean test so
events cannot overwrite each other.

- [ ] **Step 4: Run the full SkillAdaptor test file**

```bash
pytest tests/evolution/test_skilladaptor_executor.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the executor integration**

```bash
git add src/rsebench/evolution/skilladaptor_executor.py tests/evolution/test_skilladaptor_executor.py
git commit -m "feat: qualify SkillAdaptor execution audits"
```

---

### Task 6: Freeze 5/5/20 WebShop data using repaired seed calibration

**Files:**
- Modify: `scripts/export_core1_webshop_source.py`
- Create: `scripts/calibrate_clean_webshop_validation.py`
- Create: `scripts/build_clean_webshop_qualification.py`
- Create: `tests/validation/test_clean_webshop_qualification.py`
- Create: `benchmark/validation/clean_qualification_v1/webshop_source.json`
- Create: `benchmark/validation/clean_qualification_v1/webshop_validation_selection.json`
- Create: `benchmark/validation/clean_qualification_v1/webshop.json`

**Interfaces:**
- Structural export: 5 train, 12 validation candidates, and 20 clean test.
- Calibration selection: first two seed successes plus first three seed failures in candidate order.
- Final manifest: portable `CleanEvolutionSplitManifest` with 5/5/20 tasks.

- [ ] **Step 1: Write failing selection tests**

Given candidate order `[735, 994, 1036, 1195, 893, 788, 1180]` and repaired
seed scores `{735: 0, 994: 0, 1036: 0, 1195: 1, 893: 0, 788: 1, 1180: 0}`,
assert selection is `[1195, 788, 735, 994, 1036]`. Assert the function raises
when it cannot find two successes or three failures and never reads evolved or
clean-test fields.

Assert the final clean manifest is 5/5/20, disjoint, contains no noisy text,
and records `max_iterations=3`, `max_episode_steps=15`, and
`min_sample_size=5`.

- [ ] **Step 2: Extend structural export without outcome-based selection**

Add `--test-count` defaulting to 20 and keep `--validation-candidate-count`
defaulting to 12 for this builder. Use the current official ranges and
structural selector. Do not generate or require N1/N2 overlays for clean-only
output.

- [ ] **Step 3: Implement repaired seed calibration**

Evaluate all 12 validation candidates with the frozen seed, 15-step horizon,
retrieval audit enabled, and typed failures. A candidate with an execution
failure is neither a success nor an ordinary failure and blocks selection.
Persist candidate order, per-goal reward, error mapping, selected IDs, seed
score, baseline revision, patch hashes, and token usage.

- [ ] **Step 4: Build and test the final manifest**

```bash
pytest tests/validation/test_clean_webshop_qualification.py -v
/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/webshop/.venv/bin/python scripts/export_core1_webshop_source.py --output benchmark/validation/clean_qualification_v1/webshop_source.json --validation-candidate-count 12 --test-count 20
python scripts/calibrate_clean_webshop_validation.py --source benchmark/validation/clean_qualification_v1/webshop_source.json --output benchmark/validation/clean_qualification_v1/webshop_validation_selection.json
python scripts/build_clean_webshop_qualification.py
```

Expected: tests pass; calibration has no execution failures; final sizes are
5/5/20; no selected ID depends on clean-test or evolved performance.

- [ ] **Step 5: Commit frozen WebShop qualification data**

```bash
git add scripts/export_core1_webshop_source.py scripts/calibrate_clean_webshop_validation.py scripts/build_clean_webshop_qualification.py tests/validation/test_clean_webshop_qualification.py benchmark/validation/clean_qualification_v1/webshop*.json
git commit -m "feat: freeze WebShop clean qualification split"
```

---

### Task 7: Add the budget-locked clean SkillAdaptor launcher and preflight

**Files:**
- Create: `scripts/run_clean_skilladaptor.py`
- Create: `tests/validation/test_run_clean_skilladaptor.py`
- Create: `outputs/preflight/clean-qualification-v1/webshop/preflight.json`

**Interfaces:**
- CLI accepts manifest, seed skill, fixed method seed, output root, and `--dry-run`.
- Formal executor budget is always `SkillAdaptorBudget(max_iterations=3, max_episode_steps=15)`.

- [ ] **Step 1: Write failing launcher tests**

Assert the launcher rejects non-WebShop manifests, any method seed outside the
fixed set, any manifest not sized 5/5/20, and any runtime metadata mismatch.
Assert `--dry-run` creates no command-runner or provider calls.

- [ ] **Step 2: Implement the launcher through `CleanEvolutionRunner`**

Use seed `benchmark/core1/seeds/skilladaptor_webshop.json`, set model,
temperature, thinking, split counts, patch hashes, and retrieval threshold in
parameters, and pass `CleanQualificationPolicy()`.

- [ ] **Step 3: Run tests and dry-run preflight**

```bash
pytest tests/validation/test_run_clean_skilladaptor.py tests/evolution/test_skilladaptor_executor.py -q
python scripts/run_clean_skilladaptor.py --manifest benchmark/validation/clean_qualification_v1/webshop.json --seed-skill benchmark/core1/seeds/skilladaptor_webshop.json --method-seed 20260813 --output-root outputs/preflight/clean-qualification-v1/webshop --dry-run
```

Expected: zero test failures; dry run resolves 5/5/20 tasks, reports a 15-step
horizon and 3 iterations, and creates no token event.

- [ ] **Step 4: Commit the launcher and preflight**

```bash
git add scripts/run_clean_skilladaptor.py tests/validation/test_run_clean_skilladaptor.py outputs/preflight/clean-qualification-v1/webshop/preflight.json
git commit -m "feat: launch clean SkillAdaptor qualification"
```

---

### Task 8: Verify WebShop baseline readiness

**Files:**
- Modify only when the checks expose a defect.

- [ ] **Step 1: Run all SkillAdaptor and WebShop qualification tests**

```bash
pytest tests/evolution/test_skilladaptor_executor.py tests/validation/test_clean_webshop_qualification.py tests/validation/test_run_clean_skilladaptor.py -q
```

Expected: zero failures.

- [ ] **Step 2: Verify patch replay and secret safety**

```bash
git apply --check patches/baselines/skilladaptor-clean-qualification.patch
rg -n 'sk-[A-Za-z0-9]|DEEPSEEK_API_KEY\s*[:=]\s*[^$]' patches/baselines/skilladaptor-clean-qualification.patch benchmark/validation/clean_qualification_v1/webshop*.json outputs/preflight/clean-qualification-v1/webshop
git diff --check
```

Run `git apply --check` in a clean temporary SkillAdaptor checkout after the
five prerequisite patches, not in the already patched live checkout. Expected:
patch applies; secret scan returns no credential; diff check is silent.

- [ ] **Step 3: Confirm the readiness evidence**

The preflight is ready only if goal 994 has no execution error, all selected
tasks have retrieval events, the general seed reaches each prompt, final split
is 5/5/20, and no clean-test outcome was read during threshold or validation
selection.
