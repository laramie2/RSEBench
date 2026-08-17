# Expanded N1 Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and execute a gated, larger-sample N1 validation across all four Core-1 domains.

**Architecture:** Extend the portable manifest builder without changing the released Core-1 split, add runner-level clean preflight gates, represent SkillLearn families as separate paired runs, then aggregate only comparable clean/noisy outcomes. Existing baseline adapters and token ledgers remain the execution boundary.

**Tech Stack:** Python 3.13, Pydantic, pytest, SkillOpt, SkillAdaptor, SkillLearnBench Docker harness, DeepSeek V4 Flash API.

## Global Constraints

- N1 is the only noise stage in scope.
- Clean and noisy arms use matched task IDs and one untouched clean test.
- DeepSeek thinking remains disabled.
- A failed gate stops before the next costly phase.
- Do not select tasks or families using noisy-arm test outcomes.

---

### Task 1: Freeze expanded manifests and family units

**Files:**
- Create: `scripts/build_expanded_n1_validation.py`
- Create: `tests/validation/test_expanded_n1.py`
- Create: `benchmark/validation/n1_expanded/*`

**Interfaces:**
- Produces one `EvolutionSplitManifest` for each task-domain cell and one per selected SkillLearn family.
- Uses portable locator functions from `rsebench.core1.dataset`.

- [ ] Write tests asserting 8/4/20, 8/4/20, 5/3/10 sizes and disjoint IDs.
- [ ] Write tests asserting each SkillLearn manifest contains one family only and 2/1/2 instances.
- [ ] Implement deterministic structural selection and materialize the manifests.
- [ ] Verify every artifact locator resolves and no manifest contains `/home/`.

### Task 2: Add clean preflight termination

**Files:**
- Modify: `src/rsebench/evolution/runner.py`
- Modify: `scripts/run_paired_skillopt.py`
- Modify: `scripts/run_paired_skilladaptor.py`
- Modify: `scripts/run_paired_skilllearn.py`
- Test: `tests/evolution/test_runner.py`

**Interfaces:**
- Add an optional clean-evolution gate to `PairedEvolutionRunner.run`.
- Persist `clean/preflight.json` and the token summary before raising a typed gate exception.

- [ ] Write a failing test proving a no-update or clean-reverse run never invokes the noisy arm.
- [ ] Implement the smallest runner gate preserving default behavior when disabled.
- [ ] Expose the gate through validation-run CLI flags.
- [ ] Run focused and full regression tests.

### Task 3: Run deterministic validation and seed calibration

**Files:**
- Create: `scripts/calibrate_expanded_n1.py`
- Create: `outputs/runs/n1-expanded-20260813/calibration/*`

**Interfaces:**
- Consumes expanded manifests.
- Produces seed scores, systemic failure diagnostics, selected SkillLearn families, and token ledgers.

- [ ] Validate all N1 invariants and frozen split sizes.
- [ ] Evaluate seed artifacts before any evolution call.
- [ ] Retain only non-floor/non-ceiling cells or families without reading noisy outcomes.

### Task 4: Execute expanded paired N1 experiments

**Files:**
- Create: `outputs/runs/n1-expanded-20260813/paired/*`

**Interfaces:**
- Runs the existing native baseline adapters with seed and clean gates enabled.
- Produces paired scores, artifacts, update diagnostics, and token summaries.

- [ ] Run Spreadsheet N1.
- [ ] Run OfficeQA N1.
- [ ] Run WebShop N1.
- [ ] Run each selected SkillLearn family N1 independently.
- [ ] If a first paired run has positive gap, run two additional independent paired repetitions.

### Task 5: Aggregate and verify

**Files:**
- Create: `docs/reports/expanded-n1-validation.md`
- Create: `outputs/runs/n1-expanded-20260813/aggregate.json`

**Interfaces:**
- Aggregates seed, clean, noisy, update, applicability, family, and token metrics without inventing missing scores.

- [ ] Record every gate outcome and exact run path.
- [ ] Compute instance-level and family-level SkillLearn results.
- [ ] Deduplicate token events by event ID.
- [ ] Run the complete pytest suite, manifest portability checks, secret scan, and `git diff --check`.
- [ ] Commit the verified implementation and report without pushing.
