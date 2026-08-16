# SkillLearn Clean Expansion Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove verifier-bootstrap network variance without changing the SkillLearn agent environment, then run the approved fourteen-unit clean-only expansion round.

**Architecture:** The agent continues to execute in the original content-addressed official task image. After the model tool loop ends, the executor copies a hash-audited local wheelhouse into the live container, installs the exact official pytest versions with `--no-index`, and runs the unchanged official `test_outputs.py`; a separate expansion builder freezes five family manifests, a twelve-unit formal matrix, and a two-unit failed-seed replay matrix.

**Tech Stack:** Python 3.13, pytest, Pydantic experiment contracts, Docker, pip wheelhouse, YAML experiment matrices, DeepSeek provider adapter.

## Global Constraints

- Do not modify `methods/external/skilllearnbench` or the self-feedback baseline.
- Preserve the original task image during all model/tool execution.
- Offline verifier dependencies are exactly `pytest==8.4.1` and `pytest-json-ctrf==0.3.5` plus their hash-recorded transitive wheels.
- Run only clean self-evolution; do not generate or execute N1–N4.
- Reuse offer seed `20260815`; replay only failed offer seeds `20260813` and `20260814`.
- Run the four new families with all three seeds and limit SkillLearn concurrency to three.
- Keep the existing family eligibility and bundle freeze thresholds unchanged.

---

### Task 1: Add a deterministic post-agent verifier path

**Files:**
- Modify: `src/rsebench/evolution/skilllearn_executor.py`
- Test: `tests/evolution/test_skilllearn_executor.py`

**Interfaces:**
- Consumes: optional `verifier_wheelhouse: Path` in `DockerSkillLearnBackend`.
- Produces: `_run_verifier(container, output_dir)` that either retains the legacy official-script path or performs an offline pytest invocation after the agent loop.

- [ ] **Step 1: Write the failing unit test**

Create a temporary wheelhouse and assert the backend issues `docker cp`, installs with `PIP_NO_INDEX=1`, executes `python3 -m pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py`, and writes reward from pytest's return code. Also assert the legacy backend still calls `/tests/test.sh`.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src uv run --no-sync pytest -q \
  tests/evolution/test_skilllearn_executor.py -k offline_verifier
```

Expected: fail because `verifier_wheelhouse` and `_run_verifier` do not exist.

- [ ] **Step 3: Implement the minimal post-agent verifier**

Validate the wheelhouse directory, copy it only after the model loop, install the two pinned packages with `python3 -m pip --no-index`, run the unchanged mounted `test_outputs.py`, store CTRF/reward, and include `verifier_mode=offline_pytest` in diagnostics. Do not append packages to the task Dockerfile or expose a different image to the model.

- [ ] **Step 4: Verify GREEN**

Run the focused executor tests and confirm both offline and legacy paths pass.

### Task 2: Freeze and validate the verifier wheelhouse contract

**Files:**
- Modify: `scripts/prebuild_clean_skilllearn_images.py`
- Modify: `scripts/run_clean_skilllearn.py`
- Test: `tests/validation/test_prebuild_clean_skilllearn_images.py`
- Test: `tests/validation/test_run_clean_skilllearn.py`

**Interfaces:**
- Consumes: `--verifier-wheelhouse` during image prebuild and a `verifier` object in the generated image manifest.
- Produces: manifest fields `mode`, `wheelhouse`, `wheelhouse_hash`, and exact package specs; the launcher validates the directory hash before provider initialization.

- [ ] **Step 1: Write failing manifest and launcher tests**

Assert the prebuild output records a root-relative wheelhouse locator and tree hash, the launcher rejects a missing or drifted wheelhouse before creating a provider client, and a valid manifest passes the resolved path into `DockerSkillLearnBackend`.

- [ ] **Step 2: Verify RED**

Run the two focused validation test modules and confirm failure is caused by the missing verifier manifest support.

- [ ] **Step 3: Implement the smallest manifest bridge**

Add a provider-free wheel download/preparation helper, record sorted wheel hashes, resolve the manifest-relative path, verify `sha256_tree`, and pass the validated directory to the executor. Existing manifests without a `verifier` object retain the official script behavior.

- [ ] **Step 4: Verify GREEN and legacy compatibility**

Run the focused tests and the existing clean SkillLearn launcher tests.

### Task 3: Freeze the approved five-family input and fourteen scheduled units

**Files:**
- Modify: `scripts/build_clean_skilllearn_qualification.py`
- Test: `tests/validation/test_build_clean_skilllearn_qualification.py`
- Create: `benchmark/validation/skilllearn_clean_expansion_v1/skilllearnbench/*.json`
- Create: `benchmark/validation/skilllearn_clean_expansion_v1/skilllearn_manifest.json`
- Create: `configs/experiments/skilllearn-clean-expansion-round2.yaml`
- Create: `configs/experiments/skilllearn-offer-replay-round2.yaml`
- Modify: `tests/experiments/test_preflight.py`

**Interfaces:**
- Consumes: official ordered instances for offer-letter-generator, court-form-filling, earthquake-plate-calculation, dbscan-parameter-tuning, and travel-planning.
- Produces: five family-isolated 2/1/2-or-3 manifests, a formal matrix with four families times three seeds, and a canary/replay matrix containing only the two offer attempts that previously failed for verifier-infrastructure reasons. This preserves the control-plane rule that formal cells cannot select a seed subset.

- [ ] **Step 1: Write failing split and matrix contract tests**

Assert exact family order, task IDs, 10 train / 5 validation / 13 clean-test tasks, 12 formal plus 2 replay units, DeepSeek model lock, no noise stage, and maximum concurrency three.

- [ ] **Step 2: Verify RED**

Run the focused builder and preflight tests; expect missing expansion outputs.

- [ ] **Step 3: Generate the immutable portable manifests and matrix**

Reuse `_family_split` and portable locator conversion. Keep original task ordering and the existing runtime budget. Point every matrix cell at the new hash-audited image/verifier manifest. Do not weaken the formal per-cell seed-subset prohibition.

- [ ] **Step 4: Verify GREEN**

Run the focused tests and inspect all task IDs/source hashes without provider calls.

### Task 4: Prebuild, execute, aggregate, and decide

**Files:**
- Generate: `outputs/preflight/skilllearn-clean-expansion-round2/`
- Generate: `outputs/runs/skilllearn-clean-expansion-round2-20260816/`
- Generate: `outputs/runs/skilllearn-offer-replay-round2-20260816/`
- Create after terminal results: `docs/reports/2026-08-16-skilllearn-clean-expansion-round2.md`
- Create only if the unchanged rule passes: a content-addressed release under `releases/validation/`.

**Interfaces:**
- Consumes: the fixed twelve-unit formal matrix, two-unit replay matrix, original offer seed-15 evidence, timing summaries, and token ledgers.
- Produces: combined three-seed offer evidence, four new three-seed family results, and a freeze decision.

- [ ] **Step 1: Build and re-audit all images and verifier wheels**

Run the prebuild once, then rerun with `--require-existing`. Confirm `provider_calls=0`, every task image exists, every wheel hash matches, and an offline verifier smoke reaches pytest without network access.

- [ ] **Step 2: Run experiment preflight**

Confirm exactly twelve formal plus two replay unit identities, a clean git fingerprint, no output collisions, and `all_ready=true` before provider cost is authorized.

- [ ] **Step 3: Launch and monitor the paid matrix**

Run with `--max-parallel 3 --confirm-provider-cost`. Preserve all explicit failed attempts and do not retry model failures silently.

- [ ] **Step 4: Aggregate and apply the unchanged rule**

Combine the two replayed offer seeds with the already valid seed `20260815`; report every family seed score, evolved score, accepted updates, duration, calls, and tokens. Freeze only if at least four families qualify and provide at least ten clean-test tasks.

- [ ] **Step 5: Verify and commit**

Run the complete repository test suite, fixed-denominator assertions, credential/absolute-path scans, and release integrity checks if a release exists. Commit provider-free manifests, config, code, tests, and report; keep raw trajectories under ignored outputs.
