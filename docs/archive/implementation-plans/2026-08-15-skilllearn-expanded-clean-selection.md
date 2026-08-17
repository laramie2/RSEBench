# SkillLearn Expanded Clean Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run and freeze a reproducible multi-family SkillLearn/self-feedback clean control from eight official family candidates.

**Architecture:** A dedicated experiment matrix expands the eight committed family manifests into 24 isolated family/seed units. Existing preflight, scheduler, launcher, timing, token-ledger, and aggregation contracts are reused without baseline changes; selection occurs only after every fixed-denominator clean unit is accounted for.

**Tech Stack:** Python 3.13, pytest, Pydantic experiment contracts, YAML matrices, Docker-backed SkillLearn official verifiers, DeepSeek provider adapter.

## Global Constraints

- Do not run N1–N4 or use noise applicability for clean selection.
- Do not change the SkillLearn baseline, seed skill, model, or task contents.
- Use method seeds `20260813`, `20260814`, and `20260815`.
- Limit SkillLearn concurrency to three.
- Preserve run/stage/task timing and 100% observable provider usage when returned.
- Do not freeze fewer than four families or fewer than ten clean-test tasks.

---

### Task 1: Declare and verify the expanded clean matrix

**Files:**
- Create: `configs/experiments/skilllearn-clean-expanded-v1.yaml`
- Modify: `tests/experiments/test_preflight.py`
- Create: `docs/superpowers/specs/2026-08-15-skilllearn-expanded-clean-selection-design.md`

**Interfaces:**
- Consumes: eight manifests below `benchmark/validation/clean_qualification_v2/skilllearnbench/` and `skilllearn_image_manifest.json`.
- Produces: a formal matrix with eight cells and 24 expanded method-seed units.

- [ ] **Step 1: Add a matrix contract test**

Assert eight exact families, three method seeds, total task counts `16/8/20`,
portable manifests, and `adapter_max_parallel=3`.

- [ ] **Step 2: Run the test and verify the missing matrix fails**

Run:

```bash
PYTHONPATH=src uv run pytest -q tests/experiments/test_preflight.py::test_skilllearn_expanded_clean_matrix_declares_eight_families
```

Expected: one failure with `FileNotFoundError` for
`skilllearn-clean-expanded-v1.yaml`.

- [ ] **Step 3: Add the minimal eight-cell matrix**

Declare the approved provider/model/runtime contract, the exact eight family
manifests, their `2/1/2-or-3` counts, and family/seed Docker resource keys.

- [ ] **Step 4: Verify the focused and related tests**

Run:

```bash
PYTHONPATH=src uv run pytest -q tests/experiments/test_preflight.py tests/validation/test_run_clean_qualification_matrix.py tests/validation/test_run_clean_skilllearn.py
```

Expected: all selected tests pass.

### Task 2: Preflight and launch the fixed matrix

**Files:**
- Generate: `outputs/runs/skilllearn-clean-expanded-v1-20260815/`

**Interfaces:**
- Consumes: the committed matrix and current baseline fingerprint.
- Produces: immutable scheduler identities and provider-backed clean results for 24 units.

- [ ] **Step 1: Run provider-free preflight**

```bash
PYTHONPATH=src uv run rsebench experiment preflight \
  --matrix configs/experiments/skilllearn-clean-expanded-v1.yaml
```

Expected: `provider_calls=0`, `all_ready=true`, and 24 unit identities.

- [ ] **Step 2: Start the paid matrix with bounded parallelism**

```bash
PYTHONPATH=src uv run rsebench experiment run \
  --matrix configs/experiments/skilllearn-clean-expanded-v1.yaml \
  --max-parallel 3 \
  --confirm-provider-cost
```

Expected: scheduler state covers exactly 24 units and never exceeds three
running SkillLearn units.

- [ ] **Step 3: Inspect terminal state**

```bash
PYTHONPATH=src uv run rsebench experiment status \
  --matrix configs/experiments/skilllearn-clean-expanded-v1.yaml
```

Expected: all units are completed or have an explicit typed failure/attempt
record; no result is silently omitted.

### Task 3: Aggregate, select, and freeze clean controls

**Files:**
- Generate: `outputs/runs/skilllearn-clean-expanded-v1-20260815/aggregate.json`
- Create after results: `docs/reports/2026-08-15-skilllearn-expanded-clean-selection.md`
- Create after qualification: a content-addressed SkillLearn clean selection release under `releases/validation/`.

**Interfaces:**
- Consumes: the 24 fixed matrix units, timing files, token ledgers, and exact manifests.
- Produces: per-family three-seed evidence and, only if the approved rule passes, a frozen multi-family clean control.

- [ ] **Step 1: Build the fixed-denominator aggregate**

```bash
PYTHONPATH=src uv run rsebench experiment aggregate \
  --matrix configs/experiments/skilllearn-clean-expanded-v1.yaml
```

Expected: aggregate accounts for all 24 expected unit identities.

- [ ] **Step 2: Apply the approved clean-only rule**

For every family, report completed seeds, accepted update counts, seed and
evolved held-out scores, clean gains, verifier failures, durations, calls, and
tokens. Select only families satisfying the design document; use category
coverage, test denominator, then lexical order for ties.

- [ ] **Step 3: Verify release integrity before freezing**

Run the repository test suite and provider-free release checks relevant to the
generated release. Confirm exact ordered task IDs and source hashes match the
selected committed manifests and scan committed artifacts for credentials and
absolute home paths.

- [ ] **Step 4: Commit the report and eligible release**

Commit only provider-free summaries and the content-addressed selection
release. Keep raw provider trajectories and token events under gitignored
`outputs/runs/`.
