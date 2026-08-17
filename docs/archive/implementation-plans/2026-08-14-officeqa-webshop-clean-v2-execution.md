# OfficeQA and WebShop Clean V2 Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce three valid, version-consistent clean self-evolution runs for OfficeQA/SkillOpt and WebShop/SkillAdaptor before allowing either benchmark to enter N1.

**Architecture:** Finish the currently running SkillLearn matrix without changing its checkout, then integrate the repair commit into the formal checkout. Make the v2 launchers self-identifying and portable, run zero-provider-call preflights, execute one full canary per benchmark, and only then complete the remaining fixed seeds. Keep operational validity, accepted-update stability, and positive clean efficacy as separate reported decisions.

**Tech Stack:** Python 3.13, pytest, Git worktrees, SkillOpt, SkillAdaptor, DeepSeek OpenAI-compatible API, RSEBench clean qualification manifests.

## Global Constraints

- Do not modify or restart the current SkillLearn process or its `feature/rsebench-pilot` checkout while it is running.
- Pin SkillOpt to `47fe269d75d3def79ffd90236261d26d84868ae5` and SkillAdaptor to `b26d1ab5a798f07e53048b5ff509e8535e9fa228`.
- Use method seeds `20260813`, `20260814`, and `20260815` only.
- Use `deepseek-v4-flash`, temperature `0`, and thinking disabled.
- OfficeQA uses exactly `12/12/20`, three update steps, batch size four, two workers, 12 tool turns, 4096 completion tokens, and primary gate metric `hard`.
- WebShop uses exactly `5/5/20`, at most three iterations, 15 episode steps, lexical threshold `0.10`, and minimum validation sample size five.
- Clean test outcomes never enter reflection, update generation, validation selection, or runtime repair.
- Clean and future N1 arms must use byte-identical baseline commits, patches, task IDs, task order, seed skills, method seeds, model settings, and runtime budgets.
- If code, manifest, patch hash, or runtime changes after a benchmark canary begins, increment that benchmark's configuration version and rerun all three seeds; do not combine versions.
- A run counts as operationally valid only with 100% execution coverage, no systemic runtime failure, an updated semantic artifact, at least one accepted update, and non-degrading clean score.
- Positive clean gain is reported separately and is required in at least two of three seeds before starting N1 for that benchmark.

---

### Task 1: Make the v2 launchers provenance-safe

**Files:**
- Modify: `scripts/run_clean_skillopt.py`
- Modify: `scripts/run_clean_skilladaptor.py`
- Test: `tests/validation/test_clean_skillopt_qualification.py`
- Test: `tests/validation/test_run_clean_skilladaptor.py`

**Interfaces:**
- Consumes: `CleanEvolutionSplitManifest.metadata["qualification_version"]` and the current worktree `src/rsebench` package.
- Produces: a dry-run artifact whose version equals the manifest version and whose imported executor comes from the same worktree as the launcher.

- [ ] **Step 1: Add a failing subprocess import-isolation test**

  Add a test that launches Python from the repository root with the existing environment and asserts:

  ```python
  completed = subprocess.run(
      [
          sys.executable,
          "-c",
          (
              "from pathlib import Path; "
              "from rsebench.evolution import skillopt_executor; "
              "print(Path(skillopt_executor.__file__).resolve())"
          ),
      ],
      cwd=PROJECT_ROOT,
      env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")},
      capture_output=True,
      text=True,
      check=True,
  )
  assert Path(completed.stdout.strip()).is_relative_to(PROJECT_ROOT / "src")
  ```

- [ ] **Step 2: Run the isolation test and confirm the uncontrolled environment can resolve the other worktree**

  Run:

  ```bash
  python -c 'from rsebench.evolution import skillopt_executor; print(skillopt_executor.__file__)'
  ```

  Expected before setting local `PYTHONPATH`: the path may resolve to `.worktrees/rsebench-pilot/src`; this demonstrates why formal commands must pin the current worktree's `src`.

- [ ] **Step 3: Make both launchers prefer their own `src` directory**

  Replace the current path preamble in both launchers with:

  ```python
  PROJECT_ROOT = Path(__file__).resolve().parents[1]
  for import_root in (PROJECT_ROOT, PROJECT_ROOT / "src"):
      if str(import_root) not in sys.path:
          sys.path.insert(0, str(import_root))
  ```

  Because `src` is inserted after the project root, it occupies index zero and wins over an editable installation from another worktree.

- [ ] **Step 4: Add a failing OfficeQA v2 provenance assertion**

  In the existing OfficeQA dry-run test, assert:

  ```python
  assert payload["parameters"]["qualification_version"] == "clean-qualification-v2"
  assert "evaluation.gate_metric=hard" in payload["native_command"]
  assert payload["provider_calls"] == 0
  ```

- [ ] **Step 5: Derive and validate the SkillOpt qualification version**

  Immediately after loading the SkillOpt split, add:

  ```python
  qualification_version = str(
      split.metadata.get("qualification_version") or "clean-qualification-v1"
  )
  if qualification_version not in {
      "clean-qualification-v1",
      "clean-qualification-v2",
  }:
      raise ValueError(
          f"unsupported SkillOpt qualification version: {qualification_version}"
      )
  ```

  Then replace the hard-coded parameter with:

  ```python
  "qualification_version": qualification_version,
  ```

- [ ] **Step 6: Run focused launcher tests**

  Run:

  ```bash
  PYTHONPATH="$PWD/src" pytest \
    tests/validation/test_clean_skillopt_qualification.py \
    tests/validation/test_run_clean_skilladaptor.py -q
  ```

  Expected: all selected tests pass and no provider calls are made.

### Task 2: Make WebShop calibration evidence portable

**Files:**
- Create: `benchmark/validation/clean_qualification_v2/webshop_validation_retrieval_evidence.jsonl`
- Modify: `benchmark/validation/clean_qualification_v2/webshop.json`
- Modify: `scripts/build_clean_webshop_qualification.py`
- Modify: `scripts/run_clean_skilladaptor.py`
- Test: `tests/validation/test_clean_webshop_qualification.py`
- Test: `tests/validation/test_run_clean_skilladaptor.py`

**Interfaces:**
- Consumes: the ten original retrieval/prompt-injection events for validation IDs `goal_1195`, `goal_1362`, `goal_735`, `goal_994`, and `goal_1036`.
- Produces: `metadata.calibration_retrieval_evidence_path`, resolved through the `rsebench-project://` locator, with no dependency on untracked `outputs/preflight` directories.

- [ ] **Step 1: Add a failing portability test**

  Assert that a freshly built v2 manifest contains:

  ```python
  assert v2.metadata["calibration_retrieval_evidence_path"] == (
      "rsebench-project://benchmark/validation/clean_qualification_v2/"
      "webshop_validation_retrieval_evidence.jsonl"
  )
  assert "/home/" not in v2.model_dump_json()
  ```

  Add a launcher test that places a synthetic JSONL file beneath a temporary `PROJECT_ROOT`, calls `_calibration_evidence`, and verifies both `retrieval` and `prompt_injection` exist for all five validation IDs.

- [ ] **Step 2: Run the tests and observe the missing locator failure**

  Run:

  ```bash
  PYTHONPATH="$PWD/src" pytest \
    tests/validation/test_clean_webshop_qualification.py \
    tests/validation/test_run_clean_skilladaptor.py -q
  ```

  Expected before implementation: failure because the explicit portable evidence locator does not exist.

- [ ] **Step 3: Materialize the compact evidence file**

  Create the file with exactly these ten original append-only events, one `retrieval` and one `prompt_injection` event per frozen validation ID:

  ```jsonl
  {"episode_id": "goal_1195", "event": "retrieval", "lexical_matching": true, "ranked_candidates": [{"score": 0.16, "skill_id": "webshop_constraint_check"}], "retrieved_skill_ids": ["webshop_constraint_check"], "threshold": 0.1}
  {"episode_id": "goal_1195", "event": "prompt_injection", "injected_skill_ids": ["webshop_constraint_check"]}
  {"episode_id": "goal_1362", "event": "retrieval", "lexical_matching": true, "ranked_candidates": [{"score": 0.17721518987341772, "skill_id": "webshop_constraint_check"}], "retrieved_skill_ids": ["webshop_constraint_check"], "threshold": 0.1}
  {"episode_id": "goal_1362", "event": "prompt_injection", "injected_skill_ids": ["webshop_constraint_check"]}
  {"episode_id": "goal_735", "event": "retrieval", "lexical_matching": true, "ranked_candidates": [{"score": 0.15384615384615385, "skill_id": "webshop_constraint_check"}], "retrieved_skill_ids": ["webshop_constraint_check"], "threshold": 0.1}
  {"episode_id": "goal_735", "event": "prompt_injection", "injected_skill_ids": ["webshop_constraint_check"]}
  {"episode_id": "goal_994", "event": "retrieval", "lexical_matching": true, "ranked_candidates": [{"score": 0.13157894736842105, "skill_id": "webshop_constraint_check"}], "retrieved_skill_ids": ["webshop_constraint_check"], "threshold": 0.1}
  {"episode_id": "goal_994", "event": "prompt_injection", "injected_skill_ids": ["webshop_constraint_check"]}
  {"episode_id": "goal_1036", "event": "retrieval", "lexical_matching": true, "ranked_candidates": [{"score": 0.1518987341772152, "skill_id": "webshop_constraint_check"}], "retrieved_skill_ids": ["webshop_constraint_check"], "threshold": 0.1}
  {"episode_id": "goal_1036", "event": "prompt_injection", "injected_skill_ids": ["webshop_constraint_check"]}
  ```

  Compute its SHA-256 with `sha256_file(...)` in the builder and record it in the v2 manifest metadata as `calibration_retrieval_evidence_sha256`.

- [ ] **Step 4: Resolve the explicit evidence locator**

  Add a shared project-locator helper and select the v2 evidence file before falling back to legacy `evaluation_artifacts`:

  ```python
  def _project_locator_path(locator: str) -> Path:
      prefix = "rsebench-project://"
      if locator.startswith(prefix):
          return PROJECT_ROOT / locator.removeprefix(prefix)
      path = Path(locator)
      return path if path.is_absolute() else PROJECT_ROOT / path
  ```

  In `_calibration_evidence`, if `calibration_retrieval_evidence_path` is present, load that single JSONL file and verify its SHA-256 before validating per-episode event coverage. Retain the legacy artifact lookup only for v1 manifests.

- [ ] **Step 5: Rebuild and compare the v2 WebShop manifest**

  Run:

  ```bash
  PYTHONPATH="$PWD/src" python scripts/build_clean_webshop_qualification.py \
    --output-root benchmark/validation/clean_qualification_v2
  git diff --check
  ```

  Expected: task IDs and `5/5/20` ordering are unchanged; only portable evidence metadata and its hash are added.

- [ ] **Step 6: Run the focused tests again**

  Run the Task 2 pytest command again. Expected: all selected tests pass.

### Task 3: Freeze and integrate the repaired baseline version

**Files:**
- Verify: `benchmark/registry/methods.yaml`
- Verify: `patches/baselines/skilladaptor-clean-qualification.patch`
- Verify: `patches/baselines/skillopt-officeqa-bounded-recovery.patch`

**Interfaces:**
- Consumes: completed SkillLearn matrix and repair branch commits.
- Produces: one clean formal checkout containing the exact v2 launchers/manifests and one verified external checkout per baseline.

- [ ] **Step 1: Wait for the matrix parent to terminate**

  Run:

  ```bash
  ps -p 2688964 -o pid=,stat=,etime=,cmd=
  ```

  Expected before integration: no output. If the PID changed, identify the matrix process by its exact `run_clean_qualification_matrix.py --execute --stop-on-failure` command rather than guessing.

- [ ] **Step 2: Verify both worktrees are clean**

  Run:

  ```bash
  git -C /home/nvidia/yutao/lzt/self-evolution-robustness/.worktrees/rsebench-pilot status --short
  git -C /home/nvidia/yutao/lzt/self-evolution-robustness/.worktrees/clean-qualification-fixes status --short
  ```

  Expected: no output. Commit Tasks 1-2 on `fix/clean-qualification-baselines` before integrating.

- [ ] **Step 3: Integrate the repair commits into the formal checkout**

  From the formal checkout, cherry-pick the repair commit(s) in order. Do not rewrite or delete the v1 results.

- [ ] **Step 4: Verify upstream revisions and patch state**

  Run:

  ```bash
  git -C methods/external/skillopt rev-parse HEAD
  git -C methods/external/skilladaptor rev-parse HEAD
  git -C methods/external/skillopt apply --reverse --check \
    "$PWD/patches/baselines/skillopt-officeqa-bounded-recovery.patch"
  git -C methods/external/skilladaptor apply --reverse --check \
    "$PWD/patches/baselines/skilladaptor-clean-qualification.patch"
  ```

  Expected revisions: SkillOpt `47fe269d75d3def79ffd90236261d26d84868ae5`; SkillAdaptor `b26d1ab5a798f07e53048b5ff509e8535e9fa228`. Both reverse checks exit zero, proving the recorded patches are applied.

- [ ] **Step 5: Run the regression suite from the formal checkout**

  Run:

  ```bash
  PYTHONPATH="$PWD/src" pytest -q
  ```

  Expected: the full suite passes. Save the exact count and elapsed time in the run report.

### Task 4: Execute zero-call preflights

**Files:**
- Create: `outputs/preflight/clean-qualification-v2/webshop/preflight.json`
- Create: `outputs/preflight/clean-qualification-v2/officeqa/officeqa_full/20260813/dry-run/dry_run.json`

**Interfaces:**
- Consumes: integrated v2 code and manifests.
- Produces: provider-free proof of task counts, runtime budgets, patch hashes, local imports, and OfficeQA `hard` gating.

- [ ] **Step 1: Run WebShop preflight**

  ```bash
  PYTHONPATH="$PWD/src" python scripts/run_clean_skilladaptor.py \
    --manifest benchmark/validation/clean_qualification_v2/webshop.json \
    --seed-skill benchmark/core1/seeds/skilladaptor_webshop.json \
    --method-seed 20260813 \
    --output-root outputs/preflight/clean-qualification-v2/webshop \
    --dry-run
  ```

  Expected: `provider_calls=0`, `all_ready=true`, task counts `5/5/20`, qualification version v2, and complete retrieval/prompt-injection evidence for all five validation episodes.

- [ ] **Step 2: Run OfficeQA preflight**

  ```bash
  PYTHONPATH="$PWD/src" python scripts/run_clean_skillopt.py \
    --manifest benchmark/validation/clean_qualification_v2/officeqa_full.json \
    --method-seed 20260813 \
    --output-root outputs/preflight/clean-qualification-v2/officeqa \
    --dry-run
  ```

  Expected: `provider_calls=0`, task counts `12/12/20`, qualification version v2, and native command containing `evaluation.gate_metric=hard`.

- [ ] **Step 3: Stop if either preflight differs**

  A count, hash, version, patch, import, or runtime mismatch is a configuration failure. Correct it, increment the affected configuration version if a formal canary has already started, and repeat both preflights before provider calls.

### Task 5: Run the WebShop clean v2 canary and remaining seeds

**Files:**
- Create: `outputs/runs/clean-qualification-v2-20260814/webshop/<seed>/<run-id>/result.json`

**Interfaces:**
- Consumes: WebShop v2 manifest and patched SkillAdaptor.
- Produces: three immutable clean runs, starting with seed `20260815`, which previously reached accepted updates and then died on malformed Linker JSON.

- [ ] **Step 1: Run the failure-targeted canary**

  ```bash
  PYTHONPATH="$PWD/src" python scripts/run_clean_skilladaptor.py \
    --manifest benchmark/validation/clean_qualification_v2/webshop.json \
    --seed-skill benchmark/core1/seeds/skilladaptor_webshop.json \
    --method-seed 20260815 \
    --output-root outputs/runs/clean-qualification-v2-20260814/webshop
  ```

- [ ] **Step 2: Validate the canary before continuing**

  Inspect `result.json` and require: return code zero, full train/validation/test coverage, no action-parser or Linker JSON systemic failure, `artifact_updated=true`, `accepted_update_count>=1`, and `runtime_gates_passed=true`. Record seed/evolved clean scores and gain without changing the manifest based on those scores.

- [ ] **Step 3: Run seeds 20260813 and 20260814 unchanged**

  Run the same command twice, changing only `--method-seed` to `20260813` and `20260814`.

- [ ] **Step 4: Apply the WebShop decision gates**

  Require at least two of three operationally valid runs for baseline qualification. Require at least two of three `strictly_positive_gain=true` runs before WebShop N1. If operational qualification passes but positive efficacy does not, report “baseline executes and updates, but the clean efficacy signal is insufficient for N1” and do not tune the split from clean-test outcomes.

### Task 6: Run the OfficeQA clean v2 canary and remaining seeds

**Files:**
- Create: `outputs/runs/clean-qualification-v2-20260814/officeqa_full/<seed>/<run-id>/result.json`

**Interfaces:**
- Consumes: OfficeQA v2 `12/12/20` manifest and patched SkillOpt.
- Produces: three immutable clean runs with official `hard` gating and bounded malformed-output recovery.

- [ ] **Step 1: Run the OfficeQA canary**

  ```bash
  PYTHONPATH="$PWD/src" python scripts/run_clean_skillopt.py \
    --manifest benchmark/validation/clean_qualification_v2/officeqa_full.json \
    --method-seed 20260813 \
    --output-root outputs/runs/clean-qualification-v2-20260814
  ```

- [ ] **Step 2: Validate the canary before continuing**

  Require: return code zero, 100% execution coverage, parseable-answer rate at least `0.80`, systemic provider/tool failure rate at most `0.05`, native validation metric `hard`, `artifact_updated=true`, `accepted_update_count>=1`, and `runtime_gates_passed=true`. Confirm no task exhausts 12 turns by repeating unchanged unstructured analysis.

- [ ] **Step 3: Run seeds 20260814 and 20260815 unchanged**

  Run the same command twice, changing only `--method-seed`.

- [ ] **Step 4: Apply the OfficeQA decision gates**

  Require at least two of three operationally valid runs for baseline qualification and at least two of three positive clean gains before OfficeQA N1. Preserve UID0240 and its exclusion reason in amendment metadata; do not silently reintroduce or replace tasks after observing results.

### Task 7: Aggregate, report, and freeze the N1 barrier

**Files:**
- Create: `outputs/runs/clean-qualification-v2-20260814/aggregate.json`
- Create: `docs/reports/2026-08-14-officeqa-webshop-clean-v2.md`

**Interfaces:**
- Consumes: six result files and their token ledgers.
- Produces: separate operational, update, efficacy, and N1-eligibility decisions for each benchmark.

- [ ] **Step 1: Generate the existing fixed-denominator aggregate**

  ```bash
  PYTHONPATH="$PWD/src" python scripts/aggregate_clean_qualification.py \
    --run-root outputs/runs/clean-qualification-v2-20260814 \
    --output outputs/runs/clean-qualification-v2-20260814/aggregate.json
  ```

  The global `all_benchmarks_qualified` field will remain false because this root intentionally contains only the two rerun cells. Use the `officeqa_full` and `webshop` benchmark entries for their 2/3 operational decisions; do not interpret missing Spreadsheet/SkillLearn entries as new failures.

- [ ] **Step 2: Add efficacy counts to the human report**

  For each benchmark, report all three seeds with seed score, evolved score, clean gain, accepted updates, artifact hash change, execution coverage, runtime failure categories, billed calls, and billed tokens. Explicitly count `strictly_positive_gain` rather than inferring it from `qualification.passed`.

- [ ] **Step 3: Freeze the decision**

  Enter N1 for a benchmark only when both conditions hold:

  ```text
  operationally_valid_seeds >= 2/3
  strictly_positive_clean_gain_seeds >= 2/3
  ```

  If only the first condition holds, the repair succeeded operationally but the benchmark/baseline cell still lacks a stable self-evolution signal. If the first condition fails, diagnose and version a new clean configuration before any N1 call.

- [ ] **Step 4: Verify aggregate determinism and secret safety**

  ```bash
  PYTHONPATH="$PWD/src" python scripts/aggregate_clean_qualification.py \
    --run-root outputs/runs/clean-qualification-v2-20260814 \
    --output /tmp/clean-qualification-v2.verify.json
  cmp outputs/runs/clean-qualification-v2-20260814/aggregate.json \
    /tmp/clean-qualification-v2.verify.json
  rg -n 'sk-[A-Za-z0-9_-]+' \
    outputs/runs/clean-qualification-v2-20260814 \
    docs/reports/2026-08-14-officeqa-webshop-clean-v2.md
  ```

  Expected: `cmp` is silent and the secret scan returns no matches.
