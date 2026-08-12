# Expanded Efficacy and OfficeQA Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand spreadsheet and mathematics noise-efficacy validation and repair OfficeQA calibration before running a new medium-scale paired self-evolution pilot.

**Architecture:** Add an evaluation-only lane that reuses existing evolved skill artifacts against newly materialized untouched clean-test manifests, then add larger frozen generation profiles for new paired runs. Repair OfficeQA at the data/evaluator/runtime boundaries, calibrate runtime settings on a disjoint manifest, and freeze eligible IDs before generating noise. All decisions and results remain hash-audited and use the existing SkillOpt paired runner.

**Tech Stack:** Python 3.13, Pydantic, pandas, PyYAML, pytest, Hugging Face Hub, SkillOpt, DeepSeek OpenAI-compatible API.

## Global Constraints

- Use exactly `deepseek-v4-flash` at `https://api.deepseek.com` with thinking disabled.
- Never expose or persist `DEEPSEEK_API_KEY` or `HF_TOKEN`.
- Never use clean-test scores to choose tasks, runtime settings, noise candidates, or operators.
- Calibration IDs must be disjoint from evolution train, validation, and clean test.
- Provider/tool failures are systemic failures, not zero-valued benchmark observations.
- Apply noise only to evolution train and validation; clean test remains unchanged.
- Preserve equal seed skill, task order, method seed, and budgets between paired arms.
- Use TDD for every production behavior change and commit each independently testable deliverable.

---

### Task 1: Evaluation-only expanded clean-test lane

**Files:**
- Create: `src/rsebench/evolution/artifact_evaluation.py`
- Create: `scripts/evaluate_skillopt_artifacts.py`
- Create: `tests/evolution/test_artifact_evaluation.py`
- Modify: `src/rsebench/evolution/report.py`
- Test: `tests/evolution/test_artifact_evaluation.py`

**Interfaces:**
- Consumes: `EvolutionSplitManifest`, `SkillOptExecutor.evaluate`, three skill paths, and a frozen ordered list of clean-test `TaskManifest` records.
- Produces: `ArtifactComparisonResult` with seed/clean/noisy scores, per-task scores, transition counts, paired bootstrap interval, skill hashes, and output paths.

- [ ] **Step 1: Write failing tests for task transitions and artifact reuse**

```python
def test_transition_counts_are_paired_by_task_id():
    counts = count_transitions(
        clean={"a": 1.0, "b": 0.0, "c": 1.0, "d": 0.0},
        noisy={"a": 0.0, "b": 1.0, "c": 1.0, "d": 0.0},
    )
    assert counts.model_dump() == {
        "clean_correct_noisy_wrong": 1,
        "clean_wrong_noisy_correct": 1,
        "both_correct": 1,
        "both_wrong": 1,
        "net_harmful_flips": 0,
    }


def test_identical_skill_hash_is_evaluated_once(tmp_path):
    executor = RecordingExecutor(score=0.5)
    result = evaluate_skill_artifacts(
        executor=executor,
        seed_skill=tmp_path / "seed.md",
        clean_skill=tmp_path / "seed.md",
        noisy_skill=tmp_path / "noisy.md",
        clean_test=[task("q1")],
        output_dir=tmp_path / "run",
    )
    assert executor.calls == 2
    assert result.seed_score == result.clean_evolved_score
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/evolution/test_artifact_evaluation.py
```

Expected: collection failure because `artifact_evaluation` does not exist.

- [ ] **Step 3: Implement immutable result contracts and transition accounting**

```python
class TransitionCounts(BaseModel):
    clean_correct_noisy_wrong: int
    clean_wrong_noisy_correct: int
    both_correct: int
    both_wrong: int
    net_harmful_flips: int


def count_transitions(
    clean: dict[str, float], noisy: dict[str, float]
) -> TransitionCounts:
    if set(clean) != set(noisy):
        raise ValueError("paired evaluation IDs differ")
    harmful = sum(clean[k] >= 1.0 and noisy[k] < 1.0 for k in clean)
    helpful = sum(clean[k] < 1.0 and noisy[k] >= 1.0 for k in clean)
    return TransitionCounts(
        clean_correct_noisy_wrong=harmful,
        clean_wrong_noisy_correct=helpful,
        both_correct=sum(clean[k] >= 1.0 and noisy[k] >= 1.0 for k in clean),
        both_wrong=sum(clean[k] < 1.0 and noisy[k] < 1.0 for k in clean),
        net_harmful_flips=harmful - helpful,
    )
```

Implement `evaluate_skill_artifacts` with hash-keyed evaluation caching and reuse
the paired bootstrap implementation in `metrics.py`.

- [ ] **Step 4: Add a CLI that loads a profile's frozen clean-test tasks**

The CLI arguments are:

```text
--profile PATH
--source-run PATH
--test-limit INTEGER
--workers INTEGER
--max-turns INTEGER
--output-root PATH
```

It loads tasks through `_load_evolution_tasks`, preserves frozen test order, finds
`seed_skill_hash`, `clean_skill_hash`, and `noisy_skill_hash` in the source
`result.json`, and resolves the corresponding skill files. It writes
`result.json`, `report.md`, and a test-task hash manifest.

- [ ] **Step 5: Run focused and regression tests**

```bash
pytest -q tests/evolution/test_artifact_evaluation.py tests/evolution/test_metrics.py tests/evolution/test_runner.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/rsebench/evolution/artifact_evaluation.py scripts/evaluate_skillopt_artifacts.py tests/evolution/test_artifact_evaluation.py src/rsebench/evolution/report.py
git commit -m "feat: evaluate evolved skills on expanded clean tests"
```

### Task 2: Frozen medium-scale spreadsheet and mathematics profiles

**Files:**
- Create: `configs/evolution/spreadsheet-expanded.yaml`
- Create: `configs/evolution/math-expanded.yaml`
- Create: `scripts/run_profiled_skillopt.py`
- Modify: `src/rsebench/generation.py`
- Modify: `scripts/run_paired_skillopt.py`
- Modify: `tests/evolution/test_noise_generation.py`
- Test: `tests/evolution/test_noise_generation.py`

**Interfaces:**
- Consumes: current split manifests and `_collect_gate_valid_records`.
- Produces: immutable 20/10/30 spreadsheet and 15/8/50 DAPO pair manifests,
  plus one command that generates a profile and executes its paired run.

- [ ] **Step 1: Write failing tests for expanded split sizes and non-overlap**

```python
def test_expanded_profile_uses_declared_disjoint_sizes(tmp_path, monkeypatch):
    summary = generate_evolution_pairs_from_profile(profile, offline=True)
    split = summary.pair_manifest
    assert len(split.train) == 20
    assert len(split.validation) == 10
    assert len(split.clean_test) == 30
    assert not ({p.task_id for p in split.train + split.validation} &
                {t.task_id for t in split.clean_test})
```

Add a DAPO fixture asserting 15/8/50 and a generation candidate budget of four
times the requested train/validation count.

- [ ] **Step 2: Run tests and verify RED**

```bash
pytest -q tests/evolution/test_noise_generation.py -k expanded
```

Expected: failure because the expanded profiles and manifest audit fields do not
exist.

- [ ] **Step 3: Add explicit profile sizes and audit metadata**

`spreadsheet-expanded.yaml` uses `failed_attempt`, model generation, and frozen
manifest order. `math-expanded.yaml` uses `flawed_partial_solution`,
`prompt_length_desc`, hard-gate backfill, candidate multiplier 4, and the current
single-error critic gates.

Add generation summary fields recording candidate pool size, selected IDs, test
IDs, and excluded IDs without changing existing manifest contracts.

Expose the body of `run_paired_skillopt.py` as:

```python
def run_manifest(args: argparse.Namespace) -> Path:
    """Execute one paired SkillOpt manifest and return its run directory."""
```

Implement `run_profiled_skillopt.py` with explicit `--profile`, `--train-limit`,
`--validation-limit`, `--test-limit`, `--max-steps`, `--batch-size`, `--workers`,
and `--max-turns` arguments. It calls generation, requires a validated manifest,
then calls `run_manifest` without a shell placeholder.

- [ ] **Step 4: Run focused tests**

```bash
pytest -q tests/evolution/test_noise_generation.py tests/noise/test_instruction.py tests/domains/test_math.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add configs/evolution/spreadsheet-expanded.yaml configs/evolution/math-expanded.yaml scripts/run_profiled_skillopt.py scripts/run_paired_skillopt.py src/rsebench/generation.py tests/evolution/test_noise_generation.py
git commit -m "feat: add medium-scale evolution profiles"
```

### Task 3: Materialize OfficeQA oracle parsed pages

**Files:**
- Create: `scripts/materialize_officeqa_parsed_pages.py`
- Create: `src/rsebench/domains/officeqa_materialization.py`
- Create: `tests/domains/test_officeqa_materialization.py`
- Modify: `src/rsebench/evolution/skillopt_executor.py`
- Test: `tests/domains/test_officeqa_materialization.py`
- External patch target: `methods/external/skillopt/skillopt/envs/officeqa/tool_runtime.py`

**Interfaces:**
- Consumes: gated Hugging Face dataset `databricks/officeqa`, `HF_TOKEN`, and the
  source file/page references in `officeqa_full.csv`.
- Produces: `data/materialized/officeqa_full/parsed/jsons/*.json` and
  `parsed/index.json` containing relative path, size, and SHA-256 for every file.

- [ ] **Step 1: Write failing tests for parsed-page index validation**

```python
def test_validate_parsed_pages_requires_every_referenced_source(tmp_path):
    rows = [{"source_files": "a.txt\r\nb.txt"}]
    write_json(tmp_path / "jsons/a.json", [])
    with pytest.raises(FileNotFoundError, match="b.json"):
        validate_officeqa_parsed_pages(rows, tmp_path)


def test_index_contains_only_relative_paths_and_hashes(tmp_path):
    index = build_parsed_page_index([tmp_path / "jsons/a.json"], tmp_path)
    assert index[0]["path"] == "jsons/a.json"
    assert len(index[0]["sha256"]) == 64
```

- [ ] **Step 2: Run tests and verify RED**

```bash
pytest -q tests/domains/test_officeqa_materialization.py
```

Expected: collection failure because the module does not exist.

- [ ] **Step 3: Implement token-safe Hugging Face materialization**

Use `snapshot_download` with:

```python
snapshot_download(
    repo_id="databricks/officeqa",
    repo_type="dataset",
    allow_patterns="treasury_bulletins_parsed/jsons/*.json",
    token=os.environ["HF_TOKEN"],
    local_dir=data_root / "raw/officeqa",
)
```

Copy or hard-link only referenced JSON files into the materialized parsed root.
Command records contain no token value.

- [ ] **Step 4: Expose parsed and transformed roots to SkillOpt**

Modify OfficeQA domain options to pass both roots:

```python
options.extend((
    f"env.data_dirs=[{corpus},{parsed_root}]",
    "env.search_mode=offline",
    "env.use_local_tools=true",
))
```

Update `tool_runtime._locate_parsed_json` only if its existing root search cannot
resolve `parsed_root / "jsons" / f"{stem}.json"`; add an external regression test
before the patch.

- [ ] **Step 5: Run focused tests**

```bash
pytest -q tests/domains/test_officeqa_materialization.py tests/evolution/test_skillopt_executor.py
cd /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt
.venv/bin/pytest -q tests/test_officeqa_candidate_order.py tests/test_officeqa_parsed_pages.py
```

Expected: all pass and no absolute secret appears in index content.

- [ ] **Step 6: Commit**

```bash
git add scripts/materialize_officeqa_parsed_pages.py src/rsebench/domains/officeqa_materialization.py tests/domains/test_officeqa_materialization.py src/rsebench/evolution/skillopt_executor.py patches/baselines/skillopt-deepseek-thinking.patch
git commit -m "feat: materialize OfficeQA oracle pages"
```

### Task 4: OfficeQA official scorer and failure taxonomy

**Files:**
- Create: `src/rsebench/domains/officeqa_scoring.py`
- Create: `tests/domains/test_officeqa_scoring.py`
- Modify: `src/rsebench/evolution/skillopt_executor.py`
- Modify: `tests/evolution/test_skillopt_executor.py`
- External patch targets:
  - `methods/external/skillopt/skillopt/envs/officeqa/evaluator.py`
  - `methods/external/skillopt/skillopt/envs/officeqa/rollout.py`

**Interfaces:**
- Consumes: ground-truth/predicted OfficeQA strings and rollout diagnostics.
- Produces: official 1%-tolerance hard score, exact diagnostic score, and one
  failure category per task.

- [ ] **Step 1: Write parity tests from the released reward function**

```python
@pytest.mark.parametrize(
    ("gold", "prediction", "expected"),
    [
        ("56117.5", "55,991.4 million dollars", 1.0),
        ("264.632", "628.855", 0.0),
        ("-0.63", "-0.630", 1.0),
    ],
)
def test_officeqa_one_percent_score(gold, prediction, expected):
    assert score_officeqa(gold, prediction, tolerance=0.01) == expected
```

Add classification tests for `missing_oracle_page`,
`external_evidence_required`, `tool_budget_exhausted`, `answer_missing`,
`provider_failure`, and `incorrect_answer`.

- [ ] **Step 2: Run tests and verify RED**

```bash
pytest -q tests/domains/test_officeqa_scoring.py
```

Expected: collection failure because the scoring module does not exist.

- [ ] **Step 3: Vendor the minimal released scoring semantics with attribution**

Implement scalar/list numeric normalization and unit compatibility required by
the 246-row dataset. Pin `tolerance=0.01`; return both `hard` and `exact` fields.
Do not import from the mutable raw checkout at runtime.

- [ ] **Step 4: Patch SkillOpt OfficeQA evaluation and fail-fast behavior**

Each result row records:

```python
{
    "hard": official_score,
    "exact": exact_score,
    "failure_category": category,
    "oracle_parsed_pages_included": bool(oracle_context),
    "oracle_parsed_pages_chars": len(oracle_context),
}
```

Abort a batch when every item has `provider_failure` or
`missing_oracle_page`. Ordinary incorrect answers remain scored observations.

- [ ] **Step 5: Run main and external tests**

```bash
pytest -q tests/domains/test_officeqa_scoring.py tests/evolution/test_skillopt_executor.py
cd /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt
.venv/bin/pytest -q tests/test_officeqa_official_scorer.py tests/test_officeqa_failures.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/rsebench/domains/officeqa_scoring.py tests/domains/test_officeqa_scoring.py src/rsebench/evolution/skillopt_executor.py tests/evolution/test_skillopt_executor.py patches/baselines/skillopt-deepseek-thinking.patch
git commit -m "fix: align OfficeQA evaluation with official scorer"
```

### Task 5: Disjoint OfficeQA runtime calibration and frozen pilot split

**Files:**
- Create: `src/rsebench/evolution/calibration.py`
- Create: `scripts/calibrate_officeqa.py`
- Create: `tests/evolution/test_calibration.py`
- Create: `configs/calibration/officeqa.yaml`
- Create: `scripts/materialize_officeqa_calibrated_split.py`
- Modify: `src/rsebench/evolution/skillopt_executor.py`

**Interfaces:**
- Consumes: a 30-task calibration-only ID list, three ordered runtime settings,
  seed skill, official scores, and failure categories.
- Produces: a calibration report, selected runtime, eligibility manifest, and a
  disjoint 12/6/20 OfficeQA split manifest.

- [ ] **Step 1: Write failing tests for calibration gates and disjoint freezing**

```python
def test_selects_first_runtime_that_passes_all_gates():
    reports = [
        report(score=0.20, parsed=0.90, systemic=0.0, eligible=20),
        report(score=0.40, parsed=0.90, systemic=0.0, eligible=18),
        report(score=0.55, parsed=0.95, systemic=0.0, eligible=20),
    ]
    assert select_runtime(reports).name == "oracle-12x4096"


def test_freeze_excludes_calibration_and_preserves_strata():
    split = freeze_officeqa_pilot(rows, calibration_ids, seed=20260812)
    assert len(split.train) == 12
    assert len(split.validation) == 6
    assert len(split.clean_test) == 20
    assert not set(calibration_ids) & set(split.all_ids)
```

- [ ] **Step 2: Run tests and verify RED**

```bash
pytest -q tests/evolution/test_calibration.py
```

Expected: collection failure because calibration functions do not exist.

- [ ] **Step 3: Implement deterministic stratified calibration selection**

Build strata from released `difficulty` and source-file-count bins `1`, `2-3`,
and `4+`. Select IDs by seeded hash order, not label correctness. Eligibility is
based only on evidence availability and systemic execution validity.

- [ ] **Step 4: Implement cumulative runtime runner**

Evaluate in order:

```yaml
runtimes:
  - {name: oracle-6x4096, max_tool_turns: 6, max_completion_tokens: 4096}
  - {name: oracle-12x4096, max_tool_turns: 12, max_completion_tokens: 4096}
  - {name: oracle-24x8192, max_tool_turns: 24, max_completion_tokens: 8192}
```

Stop at the first report satisfying score `[0.25, 0.75]`, parseable answer rate
`>=0.80`, systemic failure rate `<0.05`, and eligible count `>=12`.

- [ ] **Step 5: Freeze and audit the 12/6/20 split**

Write `data/splits/officeqa_calibrated/split_manifest.json` with calibration,
train, validation, clean-test IDs, strata, evidence eligibility, seed, and source
hashes. Assert pairwise non-overlap before writing.

- [ ] **Step 6: Run focused tests**

```bash
pytest -q tests/evolution/test_calibration.py tests/evolution/test_skillopt_executor.py tests/test_registry.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/rsebench/evolution/calibration.py scripts/calibrate_officeqa.py tests/evolution/test_calibration.py configs/calibration/officeqa.yaml scripts/materialize_officeqa_calibrated_split.py src/rsebench/evolution/skillopt_executor.py
git commit -m "feat: calibrate and freeze OfficeQA pilot"
```

### Task 6: Execute staged experiments and update the evidence report

**Files:**
- Create: `configs/evolution/officeqa-calibrated-prompt.yaml`
- Create: `configs/evolution/officeqa-calibrated-rank.yaml`
- Modify: `docs/reports/current-experiment-status.md`
- Modify: `patches/baselines/skillopt-deepseek-thinking.patch`

**Interfaces:**
- Consumes: Tasks 1–5 artifacts and existing paired SkillOpt runner.
- Produces: expanded evaluation runs, medium-scale pair manifests/runs,
  calibration evidence, efficacy decisions, and reproducible patches.

- [ ] **Step 1: Materialize OfficeQA parsed pages and run calibration**

```bash
python scripts/materialize_officeqa_parsed_pages.py
python scripts/calibrate_officeqa.py --config configs/calibration/officeqa.yaml
```

Expected: an immutable calibration report and either a selected runtime or an
explicit blocked result. Continue OfficeQA only when a runtime passes all gates.

- [ ] **Step 2: Run expanded evaluation of existing spreadsheet skills**

```bash
python scripts/evaluate_skillopt_artifacts.py \
  --profile configs/evolution/spreadsheet-expanded.yaml \
  --source-run /home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T105048200231Z-skillopt \
  --test-limit 30 --workers 2 --max-turns 1
```

Expected: 30 paired test records and a checkpoint decision.

- [ ] **Step 3: Run expanded evaluation of existing DAPO skills**

```bash
python scripts/evaluate_skillopt_artifacts.py \
  --profile configs/evolution/math-expanded.yaml \
  --source-run /home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T113615435943Z-skillopt \
  --test-limit 50 --workers 2 --max-turns 1
```

Expected: 50 paired test records and transition counts.

- [ ] **Step 4: Generate and run medium-scale spreadsheet pairs when checkpoint allows**

```bash
python scripts/run_profiled_skillopt.py \
  --profile configs/evolution/spreadsheet-expanded.yaml \
  --train-limit 20 --validation-limit 10 --test-limit 30 \
  --max-steps 3 --batch-size 5 --workers 2 --max-turns 1
```

Expected: one complete clean/noisy run with no test contamination.

- [ ] **Step 5: Generate and run medium-scale DAPO pairs when checkpoint allows**

```bash
python scripts/run_profiled_skillopt.py \
  --profile configs/evolution/math-expanded.yaml \
  --train-limit 15 --validation-limit 8 --test-limit 50 \
  --max-steps 3 --batch-size 5 --workers 2 --max-turns 1
```

Expected: one complete clean/noisy run or an explicit hard-gate generation
exhaustion record.

- [ ] **Step 6: Run calibrated OfficeQA C1 then C3**

Generate and execute `officeqa-calibrated-prompt.yaml`. If its evolution gap is
below 0.05, execute `officeqa-calibrated-rank.yaml`. Use 12/6/20, the selected
runtime, three steps, batch size 4, and two workers. Do not run C2 until both C1
and C3 are reported.

- [ ] **Step 7: Update status report with all positive, null, blocked, and invalid outcomes**

For each attempted run record exact paths, task counts, score/gain/gap/interval,
transition counts, validation trajectories, skill hashes, tokens, failures, and
the pass/fail decision against the expanded feasibility gate.

- [ ] **Step 8: Refresh reproducible external patches**

Export the complete SkillOpt external diff, include every new tracked/untracked
adapter test, and verify:

```bash
git -C /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt \
  apply --reverse --check \
  /home/nvidia/yutao/lzt/self-evolution-robustness/.worktrees/rsebench-pilot/patches/baselines/skillopt-deepseek-thinking.patch
```

Expected: exit 0.

- [ ] **Step 9: Run full verification**

```bash
pytest -q
cd /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt
.venv/bin/pytest -q
cd /home/nvidia/yutao/lzt/self-evolution-robustness/.worktrees/rsebench-pilot
git diff --check
git grep -nE 'hf_[A-Za-z0-9]{20,}|(sk-|api[_-]?key[[:space:]]*[:=][[:space:]]*)[A-Za-z0-9_-]{20,}' -- ':!.env.example'
```

Expected: all tests pass, patch check passes, formatting check is clean, and the
secret scan returns no matches.

- [ ] **Step 10: Commit**

```bash
git add configs/evolution/officeqa-calibrated-prompt.yaml configs/evolution/officeqa-calibrated-rank.yaml docs/reports/current-experiment-status.md patches/baselines/skillopt-deepseek-thinking.patch
git commit -m "experiments: expand paired efficacy validation"
```
