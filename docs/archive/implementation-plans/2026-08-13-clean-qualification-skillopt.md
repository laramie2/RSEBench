# SkillOpt Clean Qualification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materialize confirmation-scale clean SpreadsheetBench and OfficeQA manifests, expose complete SkillOpt update/coverage evidence, and run either cell through the clean-only qualification harness.

**Architecture:** The builder reads the frozen official Spreadsheet split and calibrated OfficeQA split and emits portable clean-only manifests. `SkillOptExecutor` parses the native `summary.json` and per-step result files into the shared `EvolutionExecutionAudit`. A dedicated launcher derives all formal budgets from the benchmark name, preventing accidental reuse of the earlier one-step and 3-turn OfficeQA settings.

**Tech Stack:** Python 3.13, pandas, Pydantic 2, pytest, SkillOpt native trainer/evaluator, DeepSeek V4 Flash.

## Global Constraints

- SpreadsheetBench-Verified uses exactly 20 acquisition, 10 validation, and 30 clean-test tasks.
- Spreadsheet SkillOpt uses 3 update steps, batch size 7, 2 workers, 3 tool turns, and 2048 completion tokens.
- OfficeQA Full uses exactly the frozen calibrated 12/6/20 split.
- OfficeQA SkillOpt uses 3 update steps, batch size 4, 2 workers, 12 tool turns, and 4096 completion tokens.
- OfficeQA uses the released scorer with 1% relative numeric tolerance.
- OfficeQA requires parseable-answer rate at least 0.80 and systemic provider/tool failure rate below 0.05.
- All 20 or 12 acquisition tasks must appear in native rollout results across the three steps.
- Clean test is never passed to native training with `eval_test=true`.
- Three method seeds use identical task IDs, task order, seed skill, model, and budgets.

---

### Task 1: Publish SkillOpt's accepted updates and execution coverage

**Files:**
- Modify: `src/rsebench/evolution/skillopt_executor.py`
- Modify: `tests/evolution/test_skillopt_executor.py`

**Interfaces:**
- Produces: `EvolutionArtifact.execution_audit` for every successful SkillOpt evolution.
- Reads: `native_train/summary.json`, `native_train/steps/step_*/rollout/results.jsonl`, `native_train/selection_eval_baseline/results.jsonl`, and `native_train/steps/step_*/selection_eval/results.jsonl`.
- Stable accepted-update source: `summary.json.total_accepts`.
- Produces: OfficeQA `EvaluationResult.diagnostics.execution_failures` from native rows whose `agent_ok` is false.

- [ ] **Step 1: Write failing native-audit tests**

Extend the existing fake native command runner so it writes:

```json
{
  "total_accepts": 2,
  "total_rejects": 1,
  "total_steps": 3,
  "baseline_selection_hard": 0.4,
  "best_selection_hard": 0.6
}
```

Write three rollout `results.jsonl` files whose task IDs cover
`t01` through `t20`, and validation files whose IDs cover `v01` through `v10`.
Assert:

```python
assert artifact.execution_audit is not None
assert set(artifact.execution_audit.train_task_ids) == {
    f"t{index:02d}" for index in range(1, 21)
}
assert set(artifact.execution_audit.validation_task_ids) == {
    f"v{index:02d}" for index in range(1, 11)
}
assert artifact.execution_audit.accepted_update_count == 2
assert artifact.execution_audit.metadata["total_steps"] == 3
assert artifact.execution_audit.metadata["total_rejects"] == 1
```

Add a malformed-results test proving a missing `id`/`task_id` row raises
`RuntimeError("SkillOpt execution result lacks task ID")` rather than silently
reducing coverage.

Add an OfficeQA evaluation fixture with one `provider_failure`, one
`tool_budget_exhausted`, and one ordinary incorrect answer. Assert only the
first two appear in `diagnostics.execution_failures`, while all three IDs remain
in `per_task_scores`.

- [ ] **Step 2: Run the focused tests and confirm the audit is absent**

```bash
pytest tests/evolution/test_skillopt_executor.py -v
```

Expected: the new assertions fail because `execution_audit` is `None`.

- [ ] **Step 3: Implement exact result-ID collection**

Add these private helpers to `skillopt_executor.py`:

```python
def _result_task_ids(paths: list[Path]) -> list[str]:
    task_ids: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            task_id = str(row.get("id") or row.get("task_id") or "").strip()
            if not task_id:
                raise RuntimeError("SkillOpt execution result lacks task ID")
            task_ids.add(task_id)
    return sorted(task_ids)


def _execution_audit(native_output: Path, summary: dict[str, Any]) -> EvolutionExecutionAudit:
    train_paths = sorted((native_output / "steps").glob("step_*/rollout/results.jsonl"))
    validation_paths = [native_output / "selection_eval_baseline/results.jsonl"]
    validation_paths.extend(
        sorted((native_output / "steps").glob("step_*/selection_eval/results.jsonl"))
    )
    return EvolutionExecutionAudit(
        train_task_ids=_result_task_ids(train_paths),
        validation_task_ids=_result_task_ids(validation_paths),
        accepted_update_count=int(summary.get("total_accepts", 0)),
        metadata={
            "total_steps": int(summary.get("total_steps", 0)),
            "total_rejects": int(summary.get("total_rejects", 0)),
            "total_skips": int(summary.get("total_skips", 0)),
            "baseline_selection_hard": summary.get("baseline_selection_hard"),
            "best_selection_hard": summary.get("best_selection_hard"),
        },
    )
```

Require `summary.json` for qualification-capable execution and attach the
result to `EvolutionArtifact`. Keep the raw summary in diagnostics.

In `evaluate`, when `benchmark == "officeqa_full"`, build:

```python
execution_failures = {
    task_id: (
        f"{row.get('failure_category')}: "
        f"{row.get('fail_reason') or 'native OfficeQA execution failed'}"
    )
    for task_id, row in result_rows.items()
    if row.get("agent_ok") is False
}
```

Persist it in diagnostics. For non-OfficeQA benchmarks use an empty mapping;
do not infer provider failures from ordinary zero scores.

- [ ] **Step 4: Run SkillOpt executor and bridge regression tests**

```bash
pytest tests/evolution/test_skillopt_executor.py tests/evolution/test_skillopt_bridge.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the SkillOpt audit**

```bash
git add src/rsebench/evolution/skillopt_executor.py tests/evolution/test_skillopt_executor.py
git commit -m "feat: audit SkillOpt clean evolution coverage"
```

---

### Task 2: Materialize frozen Spreadsheet and OfficeQA clean manifests

**Files:**
- Create: `scripts/build_clean_skillopt_qualification.py`
- Create: `tests/validation/test_clean_skillopt_qualification.py`
- Create: `benchmark/validation/clean_qualification_v1/spreadsheetbench_verified.json`
- Create: `benchmark/validation/clean_qualification_v1/officeqa_full.json`

**Interfaces:**
- Produces: `build_spreadsheet_clean_split() -> CleanEvolutionSplitManifest`.
- Produces: `build_officeqa_clean_split() -> CleanEvolutionSplitManifest`.
- Uses: `make_clean_split_paths_portable` from the shared harness plan.

- [ ] **Step 1: Write failing deterministic-manifest tests**

Assert all of the following:

```python
spreadsheet = build_spreadsheet_clean_split()
assert (len(spreadsheet.train), len(spreadsheet.validation), len(spreadsheet.clean_test)) == (20, 10, 30)
assert spreadsheet.metadata["runtime"] == {
    "max_steps": 3,
    "batch_size": 7,
    "workers": 2,
    "max_tool_turns": 3,
    "max_completion_tokens": 2048,
}

office = build_officeqa_clean_split()
assert (len(office.train), len(office.validation), len(office.clean_test)) == (12, 6, 20)
assert office.metadata["runtime"]["max_tool_turns"] == 12
assert office.metadata["runtime"]["max_completion_tokens"] == 4096
assert office.metadata["qualification_policy"] == {
    "min_parseable_answer_rate": 0.80,
    "max_systemic_failure_rate": 0.05,
}

for split in (spreadsheet, office):
    assert len({task.task_id for task in split.train + split.validation + split.clean_test}) == (
        len(split.train) + len(split.validation) + len(split.clean_test)
    )
    assert "noisy" not in split.model_dump_json()
```

Add a CLI test that writes to a temporary root twice and asserts the second
write is byte-identical rather than overwritten with different content.

- [ ] **Step 2: Run the manifest tests and verify the builder is absent**

```bash
pytest tests/validation/test_clean_skillopt_qualification.py -v
```

Expected: import failure for `scripts.build_clean_skillopt_qualification`.

- [ ] **Step 3: Implement Spreadsheet selection**

Read `/home/nvidia/yutao/lzt/self-evolution-robustness/data/splits/spreadsheetbench_verified/split_manifest.json`.
Select the first 20 `evolution`, first 10 `validation`, and first 30 `test`
IDs. Load tasks with `_load_evolution_tasks`, rehash each workbook with
`sha256_file`, preserve manifest order, and set metadata:

```python
{
    "qualification_version": "clean-qualification-v1",
    "baseline": "skillopt",
    "source_partition": {
        "train": "evolution",
        "validation": "validation",
        "clean_test": "test",
    },
    "runtime": {
        "max_steps": 3,
        "batch_size": 7,
        "workers": 2,
        "max_tool_turns": 3,
        "max_completion_tokens": 2048,
    },
}
```

- [ ] **Step 4: Implement OfficeQA selection**

Read the frozen
`/home/nvidia/yutao/lzt/self-evolution-robustness/data/splits/officeqa_calibrated/split_manifest.json`
without reselecting tasks. Load the exact 12 evolution, 6 validation, and 20
test IDs from `officeqa_full.csv` with `_office_task`. Preserve parsed-page,
source-document, scorer, and evidence-eligibility metadata. Set runtime and
qualification policy exactly as asserted in Step 1.

- [ ] **Step 5: Encode portable paths and materialize**

Write both files through `make_clean_split_paths_portable`. Refuse to overwrite
an existing file whose bytes differ. Write an index
`benchmark/validation/clean_qualification_v1/skillopt_manifest.json` containing
schema version, output paths, sizes, source hashes, and the three formal method
seeds.

- [ ] **Step 6: Run tests and generate the repository manifests**

```bash
pytest tests/validation/test_clean_skillopt_qualification.py tests/core1/test_dataset.py -v
python scripts/build_clean_skillopt_qualification.py
rg -n '/home/|"noisy"' benchmark/validation/clean_qualification_v1/*.json
```

Expected: tests pass; the builder prints two paths; the final `rg` command
returns no matches.

- [ ] **Step 7: Commit the manifests**

```bash
git add scripts/build_clean_skillopt_qualification.py tests/validation/test_clean_skillopt_qualification.py benchmark/validation/clean_qualification_v1
git commit -m "feat: freeze SkillOpt clean qualification splits"
```

---

### Task 3: Add a budget-locked clean SkillOpt launcher

**Files:**
- Create: `scripts/run_clean_skillopt.py`
- Create: `tests/validation/test_run_clean_skillopt.py`

**Interfaces:**
- Produces: `run_manifest(manifest: Path, *, method_seed: int, output_root: Path) -> Path`.
- Consumes: one portable `CleanEvolutionSplitManifest` and the baseline's native initial skill.
- Rejects any runtime metadata that differs from the hard-coded formal settings.

- [ ] **Step 1: Write failing launcher tests with a fake runner**

Parameterize the two benchmarks and assert the executor budgets are exactly:

```python
EXPECTED = {
    "spreadsheetbench_verified": SkillOptBudget(
        max_steps=3,
        batch_size=7,
        workers=2,
        max_turns=3,
        max_completion_tokens=2048,
    ),
    "officeqa_full": SkillOptBudget(
        max_steps=3,
        batch_size=4,
        workers=2,
        max_turns=12,
        max_completion_tokens=4096,
    ),
}
```

Assert the launcher passes `CleanQualificationPolicy()` for Spreadsheet and
`CleanQualificationPolicy(min_parseable_answer_rate=0.80,
max_systemic_failure_rate=0.05)` for OfficeQA. Assert no seed-score interval or
N1 stage argument exists in the CLI parser.

- [ ] **Step 2: Run and confirm the launcher is absent**

```bash
pytest tests/validation/test_run_clean_skillopt.py -v
```

Expected: import failure for `scripts.run_clean_skillopt`.

- [ ] **Step 3: Implement the launcher**

The CLI accepts only:

```text
--manifest PATH
--method-seed {20260813,20260814,20260815}
--output-root PATH
```

Resolve portable paths, select the seed skill from the existing `_SEEDS`
mapping, verify manifest runtime metadata equals `EXPECTED[benchmark]`, create
`SkillOptExecutor`, and invoke `CleanEvolutionRunner.run`. Persist parameters:

```python
{
    "qualification_version": "clean-qualification-v1",
    "model": "deepseek-v4-flash",
    "thinking": "disabled",
    "temperature": 0,
    "train_tasks": len(split.train),
    "validation_tasks": len(split.validation),
    "clean_test_tasks": len(split.clean_test),
    "runtime": split.metadata["runtime"],
}
```

- [ ] **Step 4: Run launcher and runner tests**

```bash
pytest tests/validation/test_run_clean_skillopt.py tests/evolution/test_clean_runner.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the launcher**

```bash
git add scripts/run_clean_skillopt.py tests/validation/test_run_clean_skillopt.py
git commit -m "feat: launch clean SkillOpt qualification"
```

---

### Task 4: Run non-billed structural preflight for both SkillOpt cells

**Files:**
- Create: `outputs/preflight/clean-qualification-v1/skillopt/manifest_audit.json`

**Interfaces:**
- Validates paths, counts, hashes, native configuration resolution, and command construction without dispatching model calls.

- [ ] **Step 1: Add `--dry-run` to the launcher**

The dry run must resolve every artifact, build the transient clean arm, render
the native command, and write `dry_run.json`; it must not invoke
`command_runner` or create a token event.

- [ ] **Step 2: Test the dry-run boundary**

```bash
pytest tests/validation/test_run_clean_skillopt.py -k dry_run -v
```

Expected: the fake command runner has zero calls and `dry_run.json` contains
only a `clean` arm.

- [ ] **Step 3: Execute both dry runs**

```bash
python scripts/run_clean_skillopt.py --manifest benchmark/validation/clean_qualification_v1/spreadsheetbench_verified.json --method-seed 20260813 --output-root outputs/preflight/clean-qualification-v1/skillopt --dry-run
python scripts/run_clean_skillopt.py --manifest benchmark/validation/clean_qualification_v1/officeqa_full.json --method-seed 20260813 --output-root outputs/preflight/clean-qualification-v1/skillopt --dry-run
```

Expected: both commands exit 0, contain 20/10/30 and 12/6/20 respectively,
and create no provider token events.

- [ ] **Step 4: Commit dry-run support and audit**

```bash
git add scripts/run_clean_skillopt.py tests/validation/test_run_clean_skillopt.py outputs/preflight/clean-qualification-v1/skillopt/manifest_audit.json
git commit -m "test: preflight clean SkillOpt qualification"
```

---

### Task 5: Verify SkillOpt integration

**Files:**
- Modify only if focused verification identifies a defect.

- [ ] **Step 1: Run all SkillOpt, clean-runner, and manifest tests**

```bash
pytest tests/evolution/test_skillopt_executor.py tests/evolution/test_skillopt_bridge.py tests/evolution/test_skillopt_officeqa_runtime.py tests/evolution/test_clean_runner.py tests/validation/test_clean_skillopt_qualification.py tests/validation/test_run_clean_skillopt.py -q
```

Expected: zero failures.

- [ ] **Step 2: Confirm OfficeQA's calibrated source and scorer**

```bash
jq '{evolution:(.evolution|length),validation:(.validation|length),test:(.test|length)}' /home/nvidia/yutao/lzt/self-evolution-robustness/data/splits/officeqa_calibrated/split_manifest.json
rg -n 'relative|0.01|tolerance' src/rsebench/domains/officeqa_scoring.py methods/external/skillopt -g '*.py'
```

Expected: counts are 12/6/20 and the scorer path shows the 1% tolerance.

- [ ] **Step 3: Confirm a clean worktree**

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and no uncommitted SkillOpt-plan changes.
