# Validation Freeze and Modular 4×4 Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze four validation datasets and four method releases, expose modular N1–N4 plugin contracts, and run the resulting 4×4 matrix through one provider-free, fully parallel-capable control plane.

**Architecture:** Add immutable dataset/method release contracts above the existing TaskManifest, evidence, and scheduler primitives. Preserve old paths through explicit compatibility resolvers while making domain/benchmark dataset roots and validated/candidate method roots canonical. Reuse the existing scheduler after adding a validation-matrix expander and attempt-local source isolation; do not rerun clean provider experiments.

**Tech Stack:** Python 3.10+, Pydantic, PyYAML, Typer, pytest, JSON Schema, existing RSEBench evidence and scheduler modules.

## Global Constraints

- Do not make provider calls while implementing or verifying this migration.
- Do not modify, stage, or commit `docs/project-onboarding.md`.
- Preserve all historical manifests, reports, outputs, and external checkout changes.
- New manifests must contain no secret, local absolute path, raw data, output directory, or third-party source.
- New tests follow RED → GREEN; every production behavior is introduced only after its failing test is observed.
- SkillFlow validation-v1 contains exactly HWPX, Distribution, and Embedded, each with six ordered tasks.
- The formal matrix contains exactly four domains × four independent stages = 16 cells.
- Clean evidence is reused by immutable identity; no clean rerun is authorized.

---

### Task 1: Immutable DatasetRelease contract and compatibility reader

**Files:**
- Create: `src/rsebench/datasets/__init__.py`
- Create: `src/rsebench/datasets/contracts.py`
- Create: `src/rsebench/datasets/loader.py`
- Create: `tests/datasets/test_contracts.py`
- Create: `tests/datasets/test_loader.py`
- Create: `benchmark/schemas/dataset-release.schema.json`

**Interfaces:**
- Consumes: existing `rsebench.contracts.TaskManifest` and portable URI conventions.
- Produces: `DatasetRelease`, `BenchmarkDataset`, `load_dataset_release(path)`, and `resolve_dataset_artifacts(release, roots)`.

- [ ] **Step 1: Write failing DatasetRelease invariant tests**

```python
def test_dataset_release_rejects_unknown_partition_task() -> None:
    payload = release_payload()
    payload["partitions"]["test"].append("missing")
    with pytest.raises(ValueError, match="unknown task"):
        DatasetRelease.model_validate(payload)

def test_dataset_release_preserves_group_order() -> None:
    release = DatasetRelease.model_validate(release_payload())
    dataset = BenchmarkDataset(release)
    assert [task.task_id for task in dataset.group("family-a")] == ["t2", "t1"]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `PYTHONPATH=src pytest -q tests/datasets/test_contracts.py tests/datasets/test_loader.py`

Expected: collection fails because `rsebench.datasets` does not exist.

- [ ] **Step 3: Implement immutable contracts and reader**

Implement `DatasetRelease` with `schema_version`, `release_id`, domain, benchmark, version, loader, verifier, task map, tuple-valued partitions/groups, resource identities, provenance, and content hash. Validate unique/known IDs and derive the canonical hash from path-independent content. `BenchmarkDataset` returns tuples and raises typed errors for unknown partition/group names.

- [ ] **Step 4: Add portable artifact resolution and old-root fallback**

Resolve `rsebench-data://`, `rsebench-methods://`, and `rsebench-project://` without mutating release identity. The data resolver checks `data/benchmarks/<domain>/<benchmark>` first and the declared legacy locator second; it must emit `DeprecationWarning` only when the legacy locator is actually used.

- [ ] **Step 5: Export JSON Schema and verify GREEN**

Run: `PYTHONPATH=src pytest -q tests/datasets/test_contracts.py tests/datasets/test_loader.py`

Expected: all focused tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/rsebench/datasets tests/datasets benchmark/schemas/dataset-release.schema.json
git commit -m "feat: add immutable dataset release protocol"
```

### Task 2: Freeze four validation-v1 dataset releases

**Files:**
- Create: `scripts/freeze_validation_v1.py`
- Create: `tests/validation/test_freeze_validation_v1.py`
- Create: `benchmark/datasets/spreadsheet/spreadsheetbench_verified/benchmark.yaml`
- Create: `benchmark/datasets/spreadsheet/spreadsheetbench_verified/releases/validation-v1/manifest.json`
- Create: `benchmark/datasets/document/officeqa_full/benchmark.yaml`
- Create: `benchmark/datasets/document/officeqa_full/releases/validation-v1/manifest.json`
- Create: `benchmark/datasets/interactive/webshop/benchmark.yaml`
- Create: `benchmark/datasets/interactive/webshop/releases/validation-v1/manifest.json`
- Create: `benchmark/datasets/skill/skillflow_tasks/benchmark.yaml`
- Create: `benchmark/datasets/skill/skillflow_tasks/releases/validation-v1/manifest.json`

**Interfaces:**
- Consumes: the three clean-v2 source manifests and two SkillFlow selection manifests named in the approved spec.
- Produces: four deterministic DatasetRelease JSON files and `freeze_validation_v1(project_root) -> list[Path]`.

- [ ] **Step 1: Write failing exact-freeze tests**

```python
def test_skillflow_release_has_exact_three_six_task_groups() -> None:
    releases = freeze_validation_v1(ROOT)
    skillflow = load_dataset_release(next(path for path in releases if "skillflow" in str(path)))
    assert skillflow.group_names() == (
        "HWPX-Document-Automation",
        "Distribution-Center-Auditing",
        "Embedded-Data-Repair",
    )
    assert [len(skillflow.group(name)) for name in skillflow.group_names()] == [6, 6, 6]

def test_split_release_counts_are_frozen() -> None:
    expected = {
        "spreadsheetbench_verified": (20, 10, 30),
        "officeqa_full": (12, 12, 20),
        "webshop": (5, 5, 20),
    }
    for release in load_all_frozen_releases(ROOT):
        if release.benchmark in expected:
            assert tuple(len(release.partitions[name]) for name in ("train", "validation", "test")) == expected[release.benchmark]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src pytest -q tests/validation/test_freeze_validation_v1.py`

Expected: fail because the freeze script and release files do not exist.

- [ ] **Step 3: Implement deterministic migration from source manifests**

The script verifies each approved source file SHA-256 before reading it, converts existing tasks without resampling, copies source hashes into provenance, and refuses to overwrite different content. For SkillFlow it selects only the 18 approved ordered task IDs and preserves task hashes from the source manifests.

- [ ] **Step 4: Generate the four release manifests**

Run: `PYTHONPATH=src python scripts/freeze_validation_v1.py`

Expected: prints four repository-relative release paths and makes zero provider calls.

- [ ] **Step 5: Verify idempotence and GREEN**

Run twice: `PYTHONPATH=src python scripts/freeze_validation_v1.py`

Then run: `PYTHONPATH=src pytest -q tests/validation/test_freeze_validation_v1.py`

Expected: second run reports identical content; focused tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add scripts/freeze_validation_v1.py tests/validation/test_freeze_validation_v1.py benchmark/datasets
git commit -m "feat: freeze validation v1 datasets"
```

### Task 3: MethodRelease contract and validated/candidate catalog

**Files:**
- Create: `src/rsebench/methods/__init__.py`
- Create: `src/rsebench/methods/contracts.py`
- Create: `src/rsebench/methods/catalog.py`
- Create: `tests/methods/test_contracts.py`
- Create: `tests/methods/test_catalog.py`
- Create: `benchmark/schemas/method-release.schema.json`
- Modify: `.gitignore`
- Create tracked metadata under `methods/validated/*` and `methods/candidates/*`.

**Interfaces:**
- Consumes: current method registry, patch series, clean evidence manifests, and existing external clone metadata.
- Produces: `MethodRelease`, `MethodCatalog`, `load_method_release(path)`, `active_releases()`, and canonical source path resolution.

- [ ] **Step 1: Write failing lifecycle and fingerprint tests**

```python
def test_validation_v1_has_three_active_method_families_and_four_releases() -> None:
    catalog = MethodCatalog.load(ROOT / "methods")
    active = catalog.active_releases()
    assert {row.method for row in active} == {"skillopt", "skilladaptor", "skillflow"}
    assert len(active) == 4

def test_candidate_cannot_be_resolved_as_active() -> None:
    catalog = MethodCatalog.load(ROOT / "methods")
    with pytest.raises(ValueError, match="not active"):
        catalog.require_active("rethinkskill")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src pytest -q tests/methods/test_contracts.py tests/methods/test_catalog.py`

Expected: fail because method release APIs do not exist.

- [ ] **Step 3: Implement MethodRelease and catalog loader**

Validate upstream HTTPS URL, 40-character revision, patch SHA-256, harness entrypoint, environment lock, supported dataset release IDs, clean evidence references, and status. Load all release JSON files under validated methods; candidate metadata is visible but cannot satisfy `require_active`.

- [ ] **Step 4: Materialize canonical method metadata**

Create four active releases:

- SkillOpt spreadsheet fingerprint `b209b2686c902166e31062e6473075f5a87d1058759d81ce66f6864efafcc3a3`;
- SkillOpt OfficeQA fingerprint `bbf775793ff2cc1e9f22b2c530a82957ba87d05749a50f6f53657c01549d9033`;
- SkillAdaptor WebShop fingerprint `ebcfa0ccc76c5589bd95da3e7ae21a4065dd5e060f9abc207954e4cd750ef014`;
- SkillFlow fingerprint `e329b830e2a65748f5fc8736a2dd7f56781a28f400281b9ee608a85c98aca875`.

Create SkillLearn as `validated_inactive`; map every remaining registry method to candidates. Existing patch files remain content-identical and are moved with `git mv` into the corresponding canonical method `patches/` directory; compatibility lookup continues to resolve the old `patches/baselines` locator during the transition.

- [ ] **Step 5: Add source ignore and compatibility resolution**

Ignore `methods/validated/*/source/` and `methods/candidates/*/source/`. Resolve canonical source first and `methods/external/<name>` second with a warning. Never copy or stage nested third-party repositories.

- [ ] **Step 6: Verify GREEN and patch replay metadata**

Run: `PYTHONPATH=src pytest -q tests/methods/test_contracts.py tests/methods/test_catalog.py tests/experiments/test_bootstrap.py`

Expected: all focused tests pass and every tracked patch hash matches metadata.

- [ ] **Step 7: Commit Task 3**

```bash
git add .gitignore src/rsebench/methods tests/methods benchmark/schemas/method-release.schema.json methods/validated methods/candidates patches/baselines benchmark/registry
git commit -m "feat: catalog validated and candidate methods"
```

### Task 4: Stable stage-owned noise plugin interfaces

**Files:**
- Create: `src/rsebench/noise/contracts.py`
- Create: `src/rsebench/noise/registry.py`
- Create: `src/rsebench/noise/stages/{n1,n2,n3,n4}/__init__.py`
- Create: `src/rsebench/noise/stages/{n1,n2,n3,n4}/plugin.yaml`
- Modify: `src/rsebench/noise/__init__.py`
- Create: `tests/noise/test_plugin_contracts.py`
- Create: `tests/noise/test_plugin_registry.py`
- Modify: `benchmark/schemas/noise-manifest.schema.json`
- Modify: `benchmark/schemas/runtime-noise-spec.schema.json`

**Interfaces:**
- Consumes: existing TaskManifest, TrajectoryRecord, FeedbackRecord, RuntimeNoiseSpec, MutationResult, and evidence hook implementations.
- Produces: `StaticNoiseOperator`, `StaticNoiseResult`, `MethodEvidenceAdapter`, `RuntimeNoiseOperator`, `NoisePlugin`, and deterministic `discover_noise_plugins()`.

- [ ] **Step 1: Write failing discovery and stage-boundary tests**

```python
def test_discovery_finds_exactly_one_stage_package_per_stage() -> None:
    plugins = discover_noise_plugins(ROOT)
    assert tuple(plugin.stage for plugin in plugins) == ("N1", "N2", "N3", "N4")

def test_runtime_operator_cannot_register_for_static_stage() -> None:
    with pytest.raises(ValueError, match="runtime operator requires N3 or N4"):
        NoisePlugin(stage="N1", form="runtime", entrypoint="x:y", version="1")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src pytest -q tests/noise/test_plugin_contracts.py tests/noise/test_plugin_registry.py`

Expected: fail because the new contracts and stage manifests do not exist.

- [ ] **Step 3: Implement shared contracts and deterministic discovery**

Discovery scans only `src/rsebench/noise/stages/*/plugin.yaml`, rejects duplicate stages/entrypoints, sorts N1–N4, and does not require editing a central list when a stage owner adds benchmark-specific operators below their stage directory.

- [ ] **Step 4: Bridge existing N1/N2 and N3/N4 implementations**

Wrap existing static materializers and evidence mutation functions behind the new protocols without changing operator behavior. Preserve current schemas through explicit version adapters. Identity mode remains exact/structural parity; protected reward checks remain fail-closed.

- [ ] **Step 5: Verify GREEN and schema examples**

Run: `PYTHONPATH=src pytest -q tests/noise/test_plugin_contracts.py tests/noise/test_plugin_registry.py tests/evidence tests/core1/test_materialize.py`

Expected: all focused noise/evidence tests pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/rsebench/noise tests/noise benchmark/schemas
git commit -m "feat: modularize four-stage noise plugins"
```

### Task 5: Validation matrix contract and exact 16-cell expansion

**Files:**
- Create: `src/rsebench/validation/__init__.py`
- Create: `src/rsebench/validation/contracts.py`
- Create: `src/rsebench/validation/matrix.py`
- Create: `tests/validation/test_validation_matrix.py`
- Create: `benchmark/schemas/validation-matrix.schema.json`
- Create: `configs/validation/validation-v1.yaml`

**Interfaces:**
- Consumes: DatasetRelease IDs, MethodRelease IDs, discovered stage plugins, and frozen clean evidence references.
- Produces: `ValidationMatrix`, `ValidationCell`, `load_validation_matrix(path)`, and `expand_validation_cells(matrix, catalogs) -> tuple[ValidationCell, ...]`.

- [ ] **Step 1: Write failing exact-matrix tests**

```python
def test_validation_v1_expands_exactly_four_by_four() -> None:
    cells = load_and_expand(ROOT / "configs/validation/validation-v1.yaml")
    assert len(cells) == 16
    assert len({cell.cell_id for cell in cells}) == 16
    assert {cell.stage for cell in cells} == {"N1", "N2", "N3", "N4"}
    assert {cell.domain for cell in cells} == {
        "spreadsheet", "document", "interactive", "skill"
    }

def test_each_cell_reuses_domain_clean_evidence() -> None:
    cells = load_and_expand(MATRIX)
    for domain in {cell.domain for cell in cells}:
        assert len({cell.clean_evidence_hash for cell in cells if cell.domain == domain}) == 1
```

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src pytest -q tests/validation/test_validation_matrix.py`

Expected: fail because validation matrix APIs/config do not exist.

- [ ] **Step 3: Implement contracts and expander**

Validate exactly four required domains and exactly N1–N4, resolve active method release compatibility with each dataset release, bind one plugin per stage, include clean evidence identity, and compute immutable cell identities. Reject combinations, missing cells, duplicate cells, inactive methods, and mismatched clean fingerprints.

- [ ] **Step 4: Write validation-v1 config**

Reference four frozen DatasetRelease files and four active MethodRelease files. Set `cell_parallelism: 16`, `seed_parallelism: 1`, and provider/model to the frozen DeepSeek identity. Do not embed absolute paths.

- [ ] **Step 5: Verify GREEN and JSON Schema**

Run: `PYTHONPATH=src pytest -q tests/validation/test_validation_matrix.py`

Expected: all focused tests pass and matrix expansion is exactly 16.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/rsebench/validation tests/validation/test_validation_matrix.py benchmark/schemas/validation-matrix.schema.json configs/validation/validation-v1.yaml
git commit -m "feat: define frozen four by four validation matrix"
```

### Task 6: Fully parallel cell scheduler and source isolation

**Files:**
- Modify: `src/rsebench/experiments/scheduler.py`
- Create: `src/rsebench/validation/scheduler.py`
- Create: `tests/validation/test_parallel_validation_scheduler.py`
- Modify: `tests/experiments/test_scheduler.py`

**Interfaces:**
- Consumes: 16 ValidationCell records and existing ScheduledUnit/ExperimentScheduler.
- Produces: `build_validation_units(cells, run_root)`, copy-on-run workspace support, and cell-level concurrency without baseline-wide mutexes.

- [ ] **Step 1: Write failing 16-cell concurrency test**

Use a barrier-backed fake command runner that records active count. Assert all 16 cell units can enter running when `max_parallel=16`, while every attempt receives distinct output/tmp/cache/workspace paths.

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src pytest -q tests/validation/test_parallel_validation_scheduler.py`

Expected: fail because validation unit building and source isolation are missing.

- [ ] **Step 3: Implement validation units and copy-on-run**

Build one ScheduledUnit per cell. Replace baseline-wide mutable keys with precise declared resources. For `source_mode=read_only`, expose the canonical checkout without writes; for `source_mode=copy_on_run`, create an attempt-local copy/reflink and point launcher environment to it. Reject writes that resolve outside attempt roots when the method declares read-only source.

- [ ] **Step 4: Preserve resume and isolated failure behavior**

Ensure one failed/blocked/invalid cell remains in status without interrupting other futures. Resume only completed units with matching result identity. Preserve config hash and Git HEAD checks.

- [ ] **Step 5: Verify GREEN and scheduler regression suite**

Run: `PYTHONPATH=src pytest -q tests/validation/test_parallel_validation_scheduler.py tests/experiments/test_scheduler.py`

Expected: concurrency reaches 16, attempt paths are unique, resume and interruption regressions pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add src/rsebench/experiments/scheduler.py src/rsebench/validation/scheduler.py tests/validation/test_parallel_validation_scheduler.py tests/experiments/test_scheduler.py
git commit -m "feat: isolate and parallelize validation cells"
```

### Task 7: Unified validation CLI and provider-free preflight

**Files:**
- Create: `src/rsebench/validation/service.py`
- Modify: `src/rsebench/cli.py`
- Create: `tests/validation/test_validation_cli.py`
- Create: `tests/validation/test_validation_preflight.py`

**Interfaces:**
- Consumes: validation matrix loader/expander, release catalogs, plugin registry, and validation scheduler.
- Produces: `validation preflight`, `validation run`, `validation status`, and `validation aggregate` commands.

- [ ] **Step 1: Write failing CLI and zero-provider preflight tests**

```python
def test_validation_preflight_expands_16_without_provider_calls(monkeypatch) -> None:
    monkeypatch.setattr(DeepSeekClient, "complete", forbidden)
    result = runner.invoke(app, ["validation", "preflight", "--matrix", str(MATRIX)])
    assert result.exit_code == 0
    assert '"cell_count": 16' in result.stdout

def test_validation_run_requires_explicit_cost_confirmation() -> None:
    result = runner.invoke(app, ["validation", "run", "--matrix", str(MATRIX)])
    assert result.exit_code != 0
    assert "confirm-provider-cost" in result.stdout
```

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=src pytest -q tests/validation/test_validation_cli.py tests/validation/test_validation_preflight.py`

Expected: fail because the validation command group does not exist.

- [ ] **Step 3: Implement service and CLI commands**

Preflight verifies release hashes, checkout/patch fingerprints, dataset artifacts, plugin contracts, clean evidence, output isolation, and exact 16-cell expansion. Run requires `--confirm-provider-cost` and accepts `--max-parallel 16`. Status and aggregate are read-only and preserve every cell terminal state.

- [ ] **Step 4: Add compatibility aliases**

Keep old Core-1 and clean-v2 commands available. Their help text points to the new validation entrypoint; no old result or manifest is rewritten.

- [ ] **Step 5: Verify GREEN**

Run: `PYTHONPATH=src pytest -q tests/validation/test_validation_cli.py tests/validation/test_validation_preflight.py tests/evidence/test_cli.py`

Expected: all focused CLI tests pass; provider call count remains zero.

- [ ] **Step 6: Commit Task 7**

```bash
git add src/rsebench/validation/service.py src/rsebench/cli.py tests/validation/test_validation_cli.py tests/validation/test_validation_preflight.py
git commit -m "feat: add unified validation control plane"
```

### Task 8: Freeze report, collaborator map, and full verification

**Files:**
- Create: `docs/reports/2026-08-17-validation-v1-freeze.md`
- Modify: `docs/project-roadmap.md`
- Modify: `benchmark/registry/benchmarks.yaml`
- Modify: `benchmark/registry/methods.yaml`
- Modify: `benchmark/registry/adapters.yaml`
- Create: `tests/validation/test_validation_release_audit.py`

**Interfaces:**
- Consumes: every frozen release and preflight output.
- Produces: a collaborator-facing freeze report and a provider-free release audit.

- [ ] **Step 1: Write failing release-audit test**

Assert four datasets, three active method families, four active method releases, four stage plugins, 16 cells, no secrets/absolute paths, and valid local relative documentation links.

- [ ] **Step 2: Run test and verify RED**

Run: `PYTHONPATH=src pytest -q tests/validation/test_validation_release_audit.py`

Expected: fail because report/registry migration is incomplete.

- [ ] **Step 3: Write freeze report and update roadmap/registry**

Document exact task counts and SkillFlow families, source hashes, method fingerprints, harness ownership, clean evidence limitations, contributor ownership for N1–N4, and the four unified CLI commands. Mark old Core-1 paths compatibility-only.

- [ ] **Step 4: Run provider-free preflight and release audit**

Run: `PYTHONPATH=src python -m rsebench.cli validation preflight --matrix configs/validation/validation-v1.yaml`

Run: `PYTHONPATH=src pytest -q tests/validation/test_validation_release_audit.py`

Expected: preflight reports 16 ready cells and zero provider calls; audit passes.

- [ ] **Step 5: Run complete verification**

Run:

```bash
PYTHONPATH=src pytest -q
ruff check src scripts tests
git diff --check
git status --short
```

Expected: tests pass. Any pre-existing Ruff finding is reported separately and cannot be described as introduced by this migration without diff evidence. Git status contains only intentional tracked changes plus the preserved untracked `docs/project-onboarding.md`.

- [ ] **Step 6: Commit Task 8**

```bash
git add docs/reports/2026-08-17-validation-v1-freeze.md docs/project-roadmap.md benchmark/registry tests/validation/test_validation_release_audit.py
git commit -m "docs: freeze modular validation v1"
```

## Plan Self-Review

- Every approved design requirement maps to a task above.
- Dataset and method identity are implemented before matrix expansion.
- Static and runtime noise share contracts but remain stage-owned.
- Scheduler isolation is implemented before the provider-backed CLI is exposed.
- No task authorizes provider calls; the first paid action remains a later user-triggered validation run.
- The plan never stages `docs/project-onboarding.md`.
