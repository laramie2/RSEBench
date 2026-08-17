# SkillLearn and Clean Qualification Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every selected SkillLearn instance execute through evolution and verification, freeze all eight family manifests, and orchestrate the complete 33-unit clean qualification matrix with an auditable global N1 barrier.

**Architecture:** SkillLearn Docker images are content-addressed and prebuilt before formal metering; formal execution refuses an absent image instead of downloading dependencies opportunistically. Each family keeps an independent 2/1/2-or-3 split and runs all three method seeds without a seed-floor gate. A declarative matrix runner dispatches the three baseline launchers sequentially, resumes only byte-identical configurations, aggregates after each unit, and never imports or invokes an N1 launcher.

**Tech Stack:** Python 3.13, Pydantic 2, pytest, Docker, SkillLearnBench official verifiers, DeepSeek V4 Flash, YAML, append-only token ledger.

## Global Constraints

- Families are exactly: `organize-messy-files`, `offer-letter-generator`, `schedule-planning`, `dependency-vulnerability-check`, `github-repo-analytics`, `financial-analysis`, `stock-data-visualization`, and `enterprise-information-search`.
- Each family uses its first two structurally ordered instances for acquisition, third for validation, and every remaining two or three instance for clean test.
- Each family runs method seeds `20260813`, `20260814`, and `20260815`; skills never cross family boundaries.
- Seed score zero never skips evolution.
- Self-feedback mode is fixed; teacher feedback is out of scope.
- Each acquisition instance produces one evolution round, so every run has exactly two rounds.
- Docker agent budget is 16 tool turns and DeepSeek completion budget is 4096 tokens.
- Every selected instance must start a container, complete the agent boundary, and return the official verifier result.
- Docker images and dependencies are built before formal execution; formal jobs cannot perform opportunistic image builds.
- A family qualifies at 2/3 successful seeds; SkillLearnBench qualifies at 4/8 families.
- No N1 job starts unless the final aggregate says all four benchmarks qualified.

---

### Task 1: Make SkillLearn images content-addressed and prebuildable

**Files:**
- Modify: `src/rsebench/evolution/skilllearn_executor.py`
- Modify: `tests/evolution/test_skilllearn_executor.py`

**Interfaces:**
- Produces: `SkillLearnImageRecord` with task ID, context hash, image tag, image ID, and workdir.
- Produces: `DockerSkillLearnBackend.prepare(task: TaskManifest, output_dir: Path) -> SkillLearnImageRecord`.
- Adds constructor flag: `require_prebuilt: bool = False`.

- [ ] **Step 1: Write failing image-identity tests**

Create a minimal environment with Dockerfile and one dependency file. Mock
Docker commands and assert:

```python
first = backend.prepare(task, tmp_path / "first")
second = backend.prepare(task, tmp_path / "second")
assert first.context_hash == second.context_hash
assert first.image_tag == second.image_tag
assert build_commands == 1
```

Change the dependency bytes without changing mtime and assert the context hash
and tag change. With `require_prebuilt=True`, mock `docker image inspect` as
missing and assert:

```python
with pytest.raises(RuntimeError, match="prebuilt SkillLearn image is missing"):
    backend.prepare(task, tmp_path / "formal")
assert build_commands == 0
```

- [ ] **Step 2: Run the focused tests and show the mtime identity is insufficient**

```bash
pytest tests/evolution/test_skilllearn_executor.py -k 'image_identity or prebuilt' -v
```

Expected: the content-change test fails because the current tag uses path and
Dockerfile mtime.

- [ ] **Step 3: Add the image record and content hash**

Define:

```python
class SkillLearnImageRecord(StrictModel):
    task_id: str
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_tag: str
    image_id: str
    workdir: str
```

Build the same temporary context currently used by `_build_image`, excluding
the mutable `skills` directory. Compute `sha256_tree(context)` and tag the image
as `rsebench-skilllearn:<first-16-hex>`. Inspect the resulting image with:

```text
docker image inspect --format={{.Id}} <image-tag>
```

Persist `image_record.json` in the supplied output directory. If the image is
absent and `require_prebuilt=True`, raise before running `docker build`.

- [ ] **Step 4: Make `execute` consume `prepare`**

Replace direct `_build_image` use with `prepare`. Copy context hash and image ID
into `SkillLearnExecution.diagnostics`; keep container cleanup in `finally`.

- [ ] **Step 5: Run SkillLearn executor tests**

```bash
pytest tests/evolution/test_skilllearn_executor.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit content-addressed images**

```bash
git add src/rsebench/evolution/skilllearn_executor.py tests/evolution/test_skilllearn_executor.py
git commit -m "feat: prebuild audited SkillLearn images"
```

---

### Task 2: Publish SkillLearn accepted updates and execution coverage

**Files:**
- Modify: `src/rsebench/evolution/skilllearn_executor.py`
- Modify: `tests/evolution/test_skilllearn_executor.py`

**Interfaces:**
- Produces: `EvolutionArtifact.execution_audit` for clean family evolution.
- Accepted count: number of validation records with `accepted is True`.
- Train coverage: every task whose evolution round completed.
- Validation coverage: every validation task evaluated for the seed and every candidate.

- [ ] **Step 1: Extend the existing two-round validation test**

Assert:

```python
assert artifact.execution_audit is not None
assert artifact.execution_audit.train_task_ids == ["family-1", "family-2"]
assert artifact.execution_audit.validation_task_ids == ["family-3"]
assert artifact.execution_audit.accepted_update_count == 2
assert artifact.execution_audit.metadata["round_count"] == 2
assert artifact.execution_audit.metadata["validation_evaluation_count"] == 3
```

Add a candidate-rejection fixture and assert accepted count reflects only true
records while both acquisition IDs remain covered.

- [ ] **Step 2: Run the focused test and confirm the audit is absent**

```bash
pytest tests/evolution/test_skilllearn_executor.py -k evolve_uses_family_validation -v
```

Expected: the new audit assertion fails.

- [ ] **Step 3: Populate `EvolutionExecutionAudit`**

Track a train ID only after `run_evolution_round` returns. Track validation IDs
after the seed validation evaluation succeeds; repeated candidate evaluations
increase `validation_evaluation_count` but do not duplicate IDs. Attach:

```python
EvolutionExecutionAudit(
    train_task_ids=completed_train_ids,
    validation_task_ids=sorted(completed_validation_ids),
    accepted_update_count=sum(bool(row["accepted"]) for row in validation_records),
    metadata={
        "round_count": len(rounds),
        "validation_evaluation_count": (
            len(validation_tasks) * (1 + len(validation_records))
        ),
        "validation_seed_score": validation_seed_score,
        "validation_final_score": validation_score,
    },
)
```

- [ ] **Step 4: Run the complete SkillLearn executor tests**

```bash
pytest tests/evolution/test_skilllearn_executor.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit execution audit support**

```bash
git add src/rsebench/evolution/skilllearn_executor.py tests/evolution/test_skilllearn_executor.py
git commit -m "feat: audit SkillLearn evolution coverage"
```

---

### Task 3: Freeze all eight clean family manifests

**Files:**
- Create: `scripts/build_clean_skilllearn_qualification.py`
- Create: `tests/validation/test_clean_skilllearn_qualification.py`
- Create: `benchmark/validation/clean_qualification_v1/skilllearnbench/*.json`
- Create: `benchmark/validation/clean_qualification_v1/skilllearn_manifest.json`

**Interfaces:**
- Produces one portable `CleanEvolutionSplitManifest` per family.
- Produces an index with family order, sizes, hashes, instance IDs, method seeds, and seed skill hash.

- [ ] **Step 1: Write failing family-manifest tests**

Assert the family list and order exactly match Global Constraints. For every
manifest assert:

```python
assert len(split.train) == 2
assert len(split.validation) == 1
assert len(split.clean_test) in {2, 3}
assert {task.metadata["task_family"] for task in split.train + split.validation + split.clean_test} == {family}
assert [task.task_id for task in split.train] == [f"{family}-1", f"{family}-2"]
assert split.validation[0].task_id == f"{family}-3"
assert "noisy" not in split.model_dump_json()
```

Assert every `artifact_path` and `official_instance_path` is portable and
resolves to an existing instance. Assert building twice is byte-identical.

- [ ] **Step 2: Run and confirm the builder is absent**

```bash
pytest tests/validation/test_clean_skilllearn_qualification.py -v
```

Expected: import failure for `scripts.build_clean_skilllearn_qualification`.

- [ ] **Step 3: Implement deterministic family construction**

Reuse `_skilllearn_task` from `scripts/build_core1_splits.py`. Sort instance
directories by numeric suffix, require at least five, use indices 0-1 for
train, index 2 for validation, and every remaining instance for test. Rehash
each instance with `sha256_tree(instance / "environment")`. Set metadata:

```python
{
    "qualification_version": "clean-qualification-v1",
    "baseline": "skilllearn_self_feedback",
    "task_family": family,
    "feedback_mode": "self",
    "runtime": {
        "max_tool_turns": 16,
        "max_completion_tokens": 4096,
        "evolution_rounds": 2,
        "require_prebuilt_images": True,
    },
}
```

- [ ] **Step 4: Materialize and test all manifests**

```bash
python scripts/build_clean_skilllearn_qualification.py
pytest tests/validation/test_clean_skilllearn_qualification.py tests/core1/test_dataset.py -v
rg -n '/home/|"noisy"' benchmark/validation/clean_qualification_v1/skilllearnbench benchmark/validation/clean_qualification_v1/skilllearn_manifest.json
```

Expected: eight family files; tests pass; final search returns no match.

- [ ] **Step 5: Commit family manifests**

```bash
git add scripts/build_clean_skilllearn_qualification.py tests/validation/test_clean_skilllearn_qualification.py benchmark/validation/clean_qualification_v1/skilllearnbench benchmark/validation/clean_qualification_v1/skilllearn_manifest.json
git commit -m "feat: freeze SkillLearn clean qualification families"
```

---

### Task 4: Prebuild and audit every selected SkillLearn image

**Files:**
- Create: `scripts/prebuild_clean_skilllearn_images.py`
- Create: `tests/validation/test_prebuild_clean_skilllearn_images.py`
- Create: `outputs/preflight/clean-qualification-v1/skilllearn/image_manifest.json`

**Interfaces:**
- Consumes all eight portable family manifests.
- Produces one deduplicated image record per distinct build context.
- Runs before formal token metering and never reads verifier outcomes.

- [ ] **Step 1: Write failing prebuild tests with a fake Docker backend**

Assert task IDs are traversed in family/instance order, duplicate context hashes
are built once, every selected task maps to one image ID, and a failed build
records `status="failed"` plus stderr and makes the script exit nonzero.

- [ ] **Step 2: Implement the prebuild script**

Resolve manifests, call `DockerSkillLearnBackend.prepare` with
`require_prebuilt=False`, and write:

```json
{
  "schema_version": "rsebench.skilllearn-image-manifest.v1",
  "qualification_version": "clean-qualification-v1",
  "images": [],
  "task_to_context_hash": {},
  "all_ready": true
}
```

Do not execute the agent or `/tests/test.sh` during image preparation.

- [ ] **Step 3: Run tests and prebuild images**

```bash
pytest tests/validation/test_prebuild_clean_skilllearn_images.py -v
python scripts/prebuild_clean_skilllearn_images.py --manifest-root benchmark/validation/clean_qualification_v1/skilllearnbench --output outputs/preflight/clean-qualification-v1/skilllearn/image_manifest.json
```

Expected: tests pass; every selected task resolves to a present Docker image;
`all_ready` is true. The formerly interrupted `organize-messy-files` dependency
download occurs only here.

- [ ] **Step 4: Re-run in required-prebuilt mode**

```bash
python scripts/prebuild_clean_skilllearn_images.py --manifest-root benchmark/validation/clean_qualification_v1/skilllearnbench --output outputs/preflight/clean-qualification-v1/skilllearn/image_manifest.verify.json --require-existing
```

Expected: zero `docker build` commands and identical context/image mappings.

- [ ] **Step 5: Commit prebuild tooling and audit**

```bash
git add scripts/prebuild_clean_skilllearn_images.py tests/validation/test_prebuild_clean_skilllearn_images.py outputs/preflight/clean-qualification-v1/skilllearn/image_manifest.json
git commit -m "test: prebuild SkillLearn qualification images"
```

---

### Task 5: Add a 4096-token, floor-tolerant clean SkillLearn launcher

**Files:**
- Create: `configs/pilot/deepseek-v4-flash-4096.yaml`
- Create: `scripts/run_clean_skilllearn.py`
- Create: `tests/validation/test_run_clean_skilllearn.py`

**Interfaces:**
- Produces: `run_manifest(manifest: Path, *, method_seed: int, output_root: Path) -> Path`.
- Uses: `DockerSkillLearnBackend(max_turns=16, require_prebuilt=True)`.
- Uses: `SkillLearnExecutor(feedback_mode="self", evidence_spec=None)`.
- Invokes: `CleanEvolutionRunner` without any seed-score interval.

- [ ] **Step 1: Write failing launcher tests**

Assert the provider config equals the current generation config except
`max_tokens: 4096`. Assert a zero seed score still produces one `evolve` call,
two acquisition rounds, validation calls, and final clean evaluation. Assert
teacher feedback, evidence specs, non-SkillLearn manifests, wrong split sizes,
and nonformal seeds are rejected.

- [ ] **Step 2: Run and confirm launcher/config are absent**

```bash
pytest tests/validation/test_run_clean_skilllearn.py -v
```

Expected: import or file-not-found failure.

- [ ] **Step 3: Implement the fixed provider config and launcher**

The CLI accepts:

```text
--manifest PATH
--seed-skill benchmark/core1/seeds/skilllearn.md
--method-seed {20260813,20260814,20260815}
--output-root PATH
--dry-run
```

The launcher validates 2/1/2-or-3 and the runtime metadata, resolves portable
paths, uses the 4096-token provider config, and records image-manifest hash,
model, thinking, temperature, feedback mode, counts, and family. It passes
`CleanQualificationPolicy()` and never constructs a `RuntimeNoiseSpec`.

- [ ] **Step 4: Run tests and one dry run per family**

```bash
pytest tests/validation/test_run_clean_skilllearn.py tests/evolution/test_skilllearn_executor.py -q
for manifest in benchmark/validation/clean_qualification_v1/skilllearnbench/*.json; do
  python scripts/run_clean_skilllearn.py --manifest "$manifest" --seed-skill benchmark/core1/seeds/skilllearn.md --method-seed 20260813 --output-root outputs/preflight/clean-qualification-v1/skilllearn --dry-run
done
```

Expected: tests pass; eight dry runs resolve; zero provider token events.

- [ ] **Step 5: Commit launcher and config**

```bash
git add configs/pilot/deepseek-v4-flash-4096.yaml scripts/run_clean_skilllearn.py tests/validation/test_run_clean_skilllearn.py
git commit -m "feat: launch clean SkillLearn qualification"
```

---

### Task 6: Define and test the complete 33-unit matrix

**Files:**
- Create: `configs/validation/clean_qualification_v1.yaml`
- Create: `scripts/run_clean_qualification_matrix.py`
- Create: `tests/validation/test_run_clean_qualification_matrix.py`

**Interfaces:**
- Default behavior is dry-run; paid execution requires `--execute`.
- Produces: `matrix_status.json` with config hash and one record per expected unit.
- Calls only `run_clean_skillopt.py`, `run_clean_skilladaptor.py`, and `run_clean_skilllearn.py`.

- [ ] **Step 1: Write the matrix configuration**

The YAML records exact method seeds, output root
`outputs/runs/clean-qualification-20260813`, all manifest paths, launcher paths,
seed skill paths, expected sizes, budgets, and qualification version. It
contains no N1 stage, noisy manifest, or paired launcher path.

- [ ] **Step 2: Write failing matrix-expansion tests**

Assert expansion yields exactly:

```python
assert len(units) == 33
assert Counter(unit.benchmark for unit in units) == {
    "spreadsheetbench_verified": 3,
    "officeqa_full": 3,
    "webshop": 3,
    "skilllearnbench": 24,
}
assert {unit.method_seed for unit in units} == {20260813, 20260814, 20260815}
assert all("paired" not in unit.command and "N1" not in unit.command for unit in units)
```

Assert default dry-run makes zero subprocess calls. Assert `--execute` runs
units sequentially, writes status after each unit, and refuses to resume a
completed unit when config hash differs.

- [ ] **Step 3: Implement deterministic matrix orchestration**

Each unit key is:

```text
BENCHMARK[/FAMILY]/METHOD_SEED
```

Before execution, verify the Git worktree is clean and record HEAD, baseline
revisions, patch hashes, manifest hashes, image-manifest hash, model settings,
and config hash. After each subprocess returns, record exit status, run path,
result hash, and current globally deduplicated token summary. A failed unit is
recorded and the matrix continues to the next unit unless `--stop-on-failure`
is explicitly supplied.

- [ ] **Step 4: Run the matrix tests and dry run**

```bash
pytest tests/validation/test_run_clean_qualification_matrix.py -v
python scripts/run_clean_qualification_matrix.py --config configs/validation/clean_qualification_v1.yaml
```

Expected: tests pass; dry run prints 33 clean-only commands; no run directory
or token event is created.

- [ ] **Step 5: Commit matrix orchestration**

```bash
git add configs/validation/clean_qualification_v1.yaml scripts/run_clean_qualification_matrix.py tests/validation/test_run_clean_qualification_matrix.py
git commit -m "feat: orchestrate clean qualification matrix"
```

---

### Task 7: Verify implementation before paid formal execution

**Files:**
- Modify only if verification identifies a defect.

**Interfaces:**
- This checkpoint must pass before `--execute` is used.

- [ ] **Step 1: Run the complete test suite**

```bash
pytest -q
```

Expected: zero failures.

- [ ] **Step 2: Verify all manifests and dry runs**

```bash
python scripts/build_clean_skillopt_qualification.py
python scripts/build_clean_webshop_qualification.py
python scripts/build_clean_skilllearn_qualification.py
python scripts/run_clean_qualification_matrix.py --config configs/validation/clean_qualification_v1.yaml
```

Expected: builders are byte-idempotent; matrix has 33 units; no noisy arm is
printed or created.

- [ ] **Step 3: Verify environment, patches, and images**

```bash
jq '.all_ready' outputs/preflight/clean-qualification-v1/skilllearn/image_manifest.json
jq '.diagnostics.execution_failures' outputs/preflight/clean-qualification-v1/webshop/goal_994/result.json
git diff --check
git status --short
```

Expected: `true`, `{}`, no whitespace errors, and a clean worktree.

- [ ] **Step 4: Commit verification-only corrections when necessary**

If Steps 1-3 required corrections, stage the exact files shown by
`git status --short` and commit them as:

```bash
git commit -m "fix: verify clean qualification preflight"
```

Do not start formal runs from a dirty worktree.

---

### Task 8: Execute the 33 formal clean units

**Files:**
- Create: `outputs/runs/clean-qualification-20260813/matrix_status.json`
- Create: `outputs/runs/clean-qualification-20260813/BENCHMARK/*`

**Interfaces:**
- Executes one unit at a time and writes append-only evidence after every unit.
- Does not change source, manifests, patches, configs, or images during execution.

- [ ] **Step 1: Record the pre-execution revision**

```bash
git rev-parse HEAD
git status --short
```

Expected: one fixed commit and no status output.

- [ ] **Step 2: Execute the complete matrix**

```bash
python scripts/run_clean_qualification_matrix.py --config configs/validation/clean_qualification_v1.yaml --execute
```

Expected: 33 terminal unit records. Each successful unit contains seed and
clean evaluations, one clean artifact, qualification decision, report, and
token ledger; no run contains a `noisy/` directory.

- [ ] **Step 3: Audit completeness immediately after execution**

```bash
jq '{expected_units,terminal_units,completed_units,failed_units,config_hash}' outputs/runs/clean-qualification-20260813/matrix_status.json
find outputs/runs/clean-qualification-20260813 -type d -name noisy -print
```

Expected: expected and terminal units are 33; the second command prints
nothing. Failed qualification decisions are valid terminal results; interrupted
or missing units must be resumed under the identical config hash.

---

### Task 9: Aggregate, report, and enforce the N1 barrier

**Files:**
- Create: `outputs/runs/clean-qualification-20260813/aggregate.json`
- Create: `docs/reports/2026-08-13-clean-baseline-qualification.md`
- Create: `tests/validation/test_clean_qualification_report.py`

**Interfaces:**
- Uses: `scripts/aggregate_clean_qualification.py` from the shared harness plan.
- Reports: every seed, family, accepted-update count, gain, failure, and exact token usage.
- N1 eligibility is exactly `aggregate.json.all_benchmarks_qualified`.

- [ ] **Step 1: Generate the machine-readable aggregate**

```bash
python scripts/aggregate_clean_qualification.py --run-root outputs/runs/clean-qualification-20260813 --output outputs/runs/clean-qualification-20260813/aggregate.json
```

Expected: fixed three-seed denominators, eight SkillLearn families, global token
deduplication, and one explicit boolean N1 barrier.

- [ ] **Step 2: Write a failing report-consistency test**

The test loads aggregate and Markdown tables and asserts every benchmark seed
and SkillLearn family appears, numeric pass counts match, total billed tokens
match, and the report's N1 statement equals `all_benchmarks_qualified`.

- [ ] **Step 3: Render the report**

The report sections are: experimental contract, environment/preflight,
Spreadsheet, OfficeQA, WebShop, SkillLearn family matrix, aggregate 2/3 and 4/8
decisions, failures, token accounting, and N1 barrier decision. A nonqualified
benchmark is reported as baseline instability and no N1 command is scheduled.

- [ ] **Step 4: Run final verification**

```bash
pytest -q
python scripts/aggregate_clean_qualification.py --run-root outputs/runs/clean-qualification-20260813 --output /tmp/clean-qualification-aggregate.verify.json
cmp outputs/runs/clean-qualification-20260813/aggregate.json /tmp/clean-qualification-aggregate.verify.json
git diff --check
rg -n 'sk-[A-Za-z0-9]|DEEPSEEK_API_KEY\s*[:=]\s*[^$]' outputs/runs/clean-qualification-20260813 docs/reports/2026-08-13-clean-baseline-qualification.md
```

Expected: tests pass; aggregate is deterministic; diff check is silent; secret
scan finds no credential value.

- [ ] **Step 5: Commit the formal evidence and report without pushing**

```bash
git add outputs/runs/clean-qualification-20260813/aggregate.json outputs/runs/clean-qualification-20260813/matrix_status.json docs/reports/2026-08-13-clean-baseline-qualification.md tests/validation/test_clean_qualification_report.py
git commit -m "feat: qualify clean evolution across four domains"
```

Do not add raw provider credentials or transient Docker logs. Do not start N1
inside this task, even when the barrier is true; N1 requires a separately
reviewed execution handoff using the frozen qualified settings.
