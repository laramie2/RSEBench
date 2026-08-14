# Core-1 Hybrid Evidence Noise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a tested executable N1–N4 interface, materialize one L2 operator for every Core-1 domain/stage, connect the four primary baselines to deterministic N3/N4 hooks, and run a 16-cell DeepSeek V4 Flash validation screen.

**Architecture:** N1/N2 are immutable paired task/environment artifacts. N3/N4 use normalized trajectory and feedback records plus a deterministic, file-backed hook that baseline adapters call after rollout and after feedback. Every mutation is fail-closed, hash-audited, replayable, and evaluated through the existing paired clean/noisy runner on an untouched clean test split.

**Tech Stack:** Python 3.13, Pydantic 2, Typer, pytest, openpyxl, Docker, official SkillOpt/SkillLearnBench/SkillAdaptor/WebShop repositories, DeepSeek OpenAI-compatible API, append-only token ledger.

## Global Constraints

- Use only `deepseek-v4-flash` with thinking disabled for validation model calls.
- Never expose a verifier, gold workbook, reference solution, or clean-test label to a generator or updater.
- N3 cannot change reward, success, task text, or environment; N4 cannot change any trajectory field or scalar reward.
- An inapplicable runtime mutation is recorded as `applicable=false`; it never silently falls back to another operator.
- Clean and noisy arms share task IDs/order, method seed, model, turn/token budget, seed skill, validation split, and clean test.
- Mathematical datasets and historical results remain on disk but are excluded from active Core-1 registries and reports.
- All external repository modifications are captured as versioned patch files under `patches/baselines/`.
- Do not write secrets to tracked files, logs, manifests, reports, or patches.

---

## File map

### Benchmark-owned runtime interface

- Create `src/rsebench/evidence/contracts.py`: strict normalized trajectory, feedback, runtime spec, context, and audit records.
- Create `src/rsebench/evidence/operators.py`: deterministic N3 omission and N4 attribution replacement.
- Create `src/rsebench/evidence/hooks.py`: native adapter protocol, identity/noisy hook, JSON replay writing.
- Create `src/rsebench/evidence/io.py`: canonical JSON hashing and CLI file mutation.
- Create `src/rsebench/evidence/__init__.py`: public API.
- Modify `src/rsebench/cli.py`: add `evidence-mutate` and export evidence schemas.
- Create `tests/evidence/test_contracts.py`, `test_operators.py`, `test_hooks.py`, `test_cli.py`.

### Core-1 static data

- Create `src/rsebench/core1/contracts.py`: Core-1 benchmark/operator profile schemas.
- Create `src/rsebench/core1/spreadsheet.py`: unlabeled stale-sheet N2 and N1 wrapper.
- Create `src/rsebench/core1/officeqa.py`: one-axis N1 and conflicting-period N2.
- Create `src/rsebench/core1/skilllearn.py`: task-family discovery, instance-1 pairing, N1/N2 resource dispatcher.
- Create `src/rsebench/core1/webshop.py`: goal/catalog parsing, N1 history, N2 near-match manifest.
- Create `src/rsebench/core1/materialize.py`: frozen paired manifests and hard-gate reports.
- Create `src/rsebench/core1/__init__.py`.
- Create `scripts/materialize_core1.py`.
- Create `tests/core1/test_spreadsheet.py`, `test_officeqa.py`, `test_skilllearn.py`, `test_webshop.py`, `test_materialize.py`.

### Baseline bridges

- Create `src/rsebench/evolution/skillopt_evidence.py` and `tests/evolution/test_skillopt_evidence.py`.
- Modify the external SkillOpt checkout at `skillopt/gradient/reflect.py`; capture `patches/baselines/skillopt-evidence-hook.patch`.
- Create `src/rsebench/evolution/skilllearn_executor.py`, `scripts/run_paired_skilllearn.py`, and tests.
- Modify the external SkillLearnBench provider/round runner; capture `patches/baselines/skilllearn-deepseek-evidence.patch`.
- Create `src/rsebench/evolution/skilladaptor_executor.py`, `scripts/run_paired_skilladaptor.py`, and tests.
- Modify the external SkillAdaptor orchestrator; capture `patches/baselines/skilladaptor-evidence-hook.patch`.

### Configuration, execution, and report

- Modify `benchmark/registry/benchmarks.yaml`, `methods.yaml`, `noise_operators.yaml`, `splits.yaml`, and `adapters.yaml`.
- Create `configs/core1/{spreadsheetbench_verified,officeqa,skilllearnbench,webshop}/{N1,N2,N3,N4}.yaml`.
- Create `scripts/run_core1_screen.py` and `tests/test_core1_screen.py`.
- Create `docs/reports/core1-validation-status.md` from run artifacts.

---

### Task 1: Normalized evidence contracts and canonical IO

**Files:**
- Create: `src/rsebench/evidence/contracts.py`
- Create: `src/rsebench/evidence/io.py`
- Create: `src/rsebench/evidence/__init__.py`
- Test: `tests/evidence/test_contracts.py`

**Interfaces:**
- Produces: `EvidenceStage`, `TraceEvent`, `TrajectoryRecord`, `FeedbackRecord`, `RuntimeNoiseSpec`, `HookContext`, `MutationAudit`, `MutationResult`, `canonical_hash`, `read_record`, `write_record`.
- Protected invariant: Pydantic validators reject N3 reward/success changes and N4 scalar-reward changes when a `MutationResult` is assembled.

- [ ] **Step 1: Write failing contract tests**

```python
def test_runtime_spec_rejects_static_stage():
    with pytest.raises(ValueError, match="runtime stage"):
        RuntimeNoiseSpec(stage="N2", operator="x", benchmark="b", domain="d", seed=1)

def test_trajectory_event_ids_are_unique():
    event = TraceEvent(event_id="e1", step_index=0, kind="action", action="search[x]")
    with pytest.raises(ValueError, match="unique"):
        TrajectoryRecord(task_id="t", benchmark="b", events=[event, event])

def test_canonical_hash_ignores_mapping_order():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest tests/evidence/test_contracts.py -q`

Expected: collection fails because `rsebench.evidence` does not exist.

- [ ] **Step 3: Implement the strict models and canonical JSON IO**

Use `StrictModel`; define stages exactly as `N1`, `N2`, `N3`, `N4`; restrict `RuntimeNoiseSpec.stage` to `N3|N4`; require positive budget; store selector name/parameters, protected fields, failure policy, version, and seed. Hash `model_dump(mode="json")` with UTF-8 JSON sorted by key and compact separators.

- [ ] **Step 4: Run focused and existing contract tests**

Run: `pytest tests/evidence/test_contracts.py tests/test_contracts.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/evidence tests/evidence/test_contracts.py
git commit -m "feat: add normalized evolution evidence contracts"
```

### Task 2: Deterministic N3 and N4 operators

**Files:**
- Create: `src/rsebench/evidence/operators.py`
- Test: `tests/evidence/test_operators.py`

**Interfaces:**
- Consumes: records and `RuntimeNoiseSpec` from Task 1.
- Produces: `omit_selected_event(record, spec)`, `replace_feedback_attribution(record, spec, trajectory)`, and `mutate_record(record, spec)`.

- [ ] **Step 1: Write failing N3/N4 tests**

```python
def test_n3_omits_one_ranked_event_and_preserves_reward():
    spec = RuntimeNoiseSpec(stage="N3", operator="omit_critical_event", benchmark="webshop", domain="interactive", seed=7, selector="tag_priority", selector_parameters={"tags": ["required_option"]})
    result = mutate_record(webshop_trajectory(), spec)
    assert [e.event_id for e in result.output_record.events] == ["e0", "e2"]
    assert result.output_record.reward == result.input_record.reward
    assert result.audit.selected_ids == ["e1"]

def test_n4_replaces_blame_with_eligible_decoy_and_preserves_summary_reward_boundary():
    result = replace_feedback_attribution(feedback(), n4_spec(), trajectory())
    assert result.output_record.blamed_event_ids == ["e2"]
    assert result.output_record.scalar_reward == result.input_record.scalar_reward
    assert result.audit.before_fragments["blamed_event_ids"] == ["e1"]
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/evidence/test_operators.py -q`

Expected: import failure for missing operators.

- [ ] **Step 3: Implement selectors**

Implement four registered selectors only:

```text
tag_priority                 N3 generic/domain-tag selector
oracle_resource_open         N3 OfficeQA source selector
same_kind_decoy_event        N4 event selector
same_shape_decoy_resource    N4 spreadsheet/document resource selector
```

Selection is sorted by selector priority, then stable SHA-256 of
`seed:event_id`; exactly `budget=1` is supported in Core-1. No eligible target
returns a non-applicable identity `MutationResult` with a reason.

- [ ] **Step 4: Verify invariants and determinism**

Run: `pytest tests/evidence/test_operators.py -q`

Expected: all pass, including repeated calls producing identical hashes and
different seeds changing only tie breaks.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/evidence/operators.py tests/evidence/test_operators.py
git commit -m "feat: add deterministic runtime evidence operators"
```

### Task 3: Hook, replay pack, and public CLI

**Files:**
- Create: `src/rsebench/evidence/hooks.py`
- Modify: `src/rsebench/cli.py`
- Modify: `benchmark/schemas/`
- Test: `tests/evidence/test_hooks.py`
- Test: `tests/evidence/test_cli.py`

**Interfaces:**
- Produces: `EvidenceAdapter` protocol and `EvidenceNoiseHook.after_rollout` / `after_feedback`.
- CLI: `rsebench evidence-mutate --spec SPEC --input INPUT --output OUTPUT --audit AUDIT [--trajectory TRAJECTORY]`.

- [ ] **Step 1: Write failing identity, noisy, and CLI tests**

Identity must return the same object by identity when no spec is configured.
Noisy mode must write `input.json`, `output.json`, and `audit.json` below
`<run>/mutation_audit/<arm>/<task>/<stage>/`. CLI output must match direct API
output byte-for-byte.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/evidence/test_hooks.py tests/evidence/test_cli.py -q`

- [ ] **Step 3: Implement hook and CLI**

The hook calls adapter normalization, Task 2 mutation, adapter denormalization,
then writes a replay pack atomically. Clean/identity mode bypasses normalization
to guarantee native parity. CLI accepts normalized JSON only.

- [ ] **Step 4: Export schemas and verify**

Run:

```bash
rsebench export-schemas
pytest tests/evidence tests/test_contracts.py -q
```

Expected: evidence schemas exist and all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/evidence src/rsebench/cli.py benchmark/schemas tests/evidence
git commit -m "feat: expose replayable evidence mutation hooks"
```

### Task 4: Core-1 profiles and active registry migration

**Files:**
- Create: `src/rsebench/core1/contracts.py`
- Modify: `benchmark/registry/benchmarks.yaml`
- Modify: `benchmark/registry/methods.yaml`
- Modify: `benchmark/registry/noise_operators.yaml`
- Modify: `benchmark/registry/splits.yaml`
- Modify: `benchmark/registry/adapters.yaml`
- Test: `tests/core1/test_registry.py`

**Interfaces:**
- Produces: `Core1Profile` with one exact operator per N1–N4 and one primary method per domain.

- [ ] **Step 1: Write failing registry test**

Assert the active Core-1 set is exactly:

```python
{
  "spreadsheetbench_verified": ("spreadsheet", "skillopt"),
  "officeqa_full": ("document", "skillopt"),
  "skilllearnbench": ("skill_learning", "skilllearn_self_feedback"),
  "webshop": ("interactive", "skilladaptor"),
}
```

Assert active operator stages equal `N1..N4` for every domain and no active
entry has domain `math`.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/core1/test_registry.py -q`

- [ ] **Step 3: Update registries**

Pin these new commits:

```text
SkillLearnBench a0da045a8bf64b8a8ff20730c4d6ef10dc4e2c5b
WebShop         64fa2a5c15c7daa698b9ac93f5bb5437b634c9bd
SkillAdaptor    b26d1ab5a798f07e53048b5ff509e8535e9fa228
RethinkSkill    4138419afc00a1fa3ff0885c0bb1618e18258354
```

Mark legacy math entries `active: false` rather than deleting them. Register
the 16 exact operator IDs from the design spec.

- [ ] **Step 4: Run registry verification**

Run: `rsebench registry-check && pytest tests/core1/test_registry.py tests/test_registry.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/core1/contracts.py benchmark/registry tests/core1/test_registry.py
git commit -m "feat: register four-domain core1 benchmark"
```

### Task 5: SpreadsheetBench-Verified N1/N2 static pairs

**Files:**
- Create: `src/rsebench/core1/spreadsheet.py`
- Modify: `src/rsebench/domains/spreadsheet.py`
- Test: `tests/core1/test_spreadsheet.py`

**Interfaces:**
- Produces: `build_spreadsheet_n1_pair(task, seed)` and `build_spreadsheet_n2_pair(task, output_path, seed)`.

- [ ] **Step 1: Write failing fixture tests**

Test N1 preserves the original instruction as a prefix, changes exactly one
parsed constraint, and excludes gold range values. Test N2 adds one realistic
prior-period sheet, preserves every original sheet digest, contains no explicit
`STALE`, `DECOY`, `OLD`, or `REFERENCE ONLY` warning, and passes the existing
spreadsheet hard gates.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/core1/test_spreadsheet.py -q`

- [ ] **Step 3: Implement N1/N2**

Reuse existing task loading and range validation. N1 wraps the already
validated failed-attempt data for the pilot. N2 copies a non-answer source
sheet, applies year offset `-1` and seeded ±3–7% numeric perturbation only to
the copy, and names it from `<source>_<prior-year-or-previous>`.

- [ ] **Step 4: Run domain tests**

Run: `pytest tests/core1/test_spreadsheet.py tests/domains/test_spreadsheet.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/core1/spreadsheet.py src/rsebench/domains/spreadsheet.py tests/core1/test_spreadsheet.py
git commit -m "feat: materialize spreadsheet core1 static noise"
```

### Task 6: OfficeQA N1/N2 static pairs

**Files:**
- Create: `src/rsebench/core1/officeqa.py`
- Modify: `src/rsebench/domains/officeqa.py`
- Test: `tests/core1/test_officeqa.py`

**Interfaces:**
- Produces: `build_officeqa_n1_pair(task, seed)` and `build_conflicting_period_fixture(task, corpus, seed)`.

- [ ] **Step 1: Write failing tests with three real-style Treasury snippets**

N1 must change exactly one question axis and exclude normalized answers. N2 must
select a non-gold document sharing entity/table vocabulary and a different
period/unit, keep every gold document exactly once in top-3, and pass the
existing leakage validator.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/core1/test_officeqa.py -q`

- [ ] **Step 3: Implement the one-axis renderer and conflicting-source ranker**

Use deterministic question-axis rules first. Use DeepSeek only when no rule
matches, requiring structured `{axis, original, replacement, note}` output and
then applying the same rule validator. Rank documents by entity overlap plus
period mismatch; never synthesize Treasury text.

- [ ] **Step 4: Run OfficeQA tests**

Run: `pytest tests/core1/test_officeqa.py tests/domains/test_officeqa.py tests/domains/test_officeqa_scoring.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/core1/officeqa.py src/rsebench/domains/officeqa.py tests/core1/test_officeqa.py
git commit -m "feat: materialize officeqa core1 static noise"
```

### Task 7: SkillLearnBench family data and N1/N2 dispatcher

**Files:**
- Create: `src/rsebench/core1/skilllearn.py`
- Test: `tests/core1/test_skilllearn.py`

**Interfaces:**
- Produces: `discover_skilllearn_families(root)`, `build_skilllearn_split(root, families)`, `build_skilllearn_n1_pair(instance1, seed)`, and `build_skilllearn_n2_pair(instance1, output_root, seed)`.

- [ ] **Step 1: Write failing tests against the pinned checkout**

Assert 20 families and 100 instances are found; acquisition is exactly
`<family>-1`; test instances are all remaining siblings; tests/solution are not
copied into learner-visible artifacts. Fixture tests cover PDF/form, XLSX/data,
software/config, media, and file-organization dispatcher branches.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/core1/test_skilllearn.py -q`

- [ ] **Step 3: Implement family discovery and resource dispatcher**

Copy only `instruction.md`, `task.toml`, and `environment/` into noisy
acquisition artifacts. Preserve original resource hashes. Add exactly one
competing resource with a manifest declaring source, transformation, and
protected output paths.

- [ ] **Step 4: Verify real checkout invariants**

Run: `pytest tests/core1/test_skilllearn.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/core1/skilllearn.py tests/core1/test_skilllearn.py
git commit -m "feat: add skilllearn core1 acquisition pairs"
```

### Task 8: WebShop goal/catalog N1/N2 data

**Files:**
- Create: `src/rsebench/core1/webshop.py`
- Test: `tests/core1/test_webshop.py`

**Interfaces:**
- Produces: `parse_goal_constraints`, `select_near_match`, `build_webshop_n1_context`, and `build_webshop_n2_overlay`.

- [ ] **Step 1: Write failing synthetic-catalog tests**

Require the near-match product to come from the catalog, match category, violate
exactly one hard constraint, differ from all valid targets, and leave at least
one valid target reachable. N1 cannot alter the original goal string. N2 output
is an ordered product-ID overlay, not a rewritten catalog.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/core1/test_webshop.py -q`

- [ ] **Step 3: Implement deterministic parsing and selection**

Support category text, attributes/options, and price upper bounds found in
WebShop goal records. Score near matches by satisfied constraints, lexical
overlap, then seeded hash. Store promoted IDs and inverse original positions.

- [ ] **Step 4: Verify**

Run: `pytest tests/core1/test_webshop.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/core1/webshop.py tests/core1/test_webshop.py
git commit -m "feat: add webshop core1 static overlays"
```

### Task 9: Unified static materializer and runtime specs

**Files:**
- Create: `src/rsebench/core1/materialize.py`
- Create: `src/rsebench/core1/__init__.py`
- Create: `scripts/materialize_core1.py`
- Create: `configs/core1/**/{N1,N2,N3,N4}.yaml`
- Test: `tests/core1/test_materialize.py`

**Interfaces:**
- Produces: `materialize_core1_profile(profile_path)` and fixed artifacts under `benchmark/core1/`.

- [ ] **Step 1: Write failing end-to-end fixture test**

For one fixture per domain, assert N1/N2 produce paired manifests and N3/N4
produce strict runtime specs; clean-test IDs never appear in static noisy
records; all manifests carry operator version, seed, hashes, gates, and source
commit.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/core1/test_materialize.py -q`

- [ ] **Step 3: Implement profiles and materializer**

The 16 YAML files fix operator, selector, L2 parameters, split sizes, primary
method, model, and token cap. Runtime specs use `budget=1` and
`record_not_applicable`.

- [ ] **Step 4: Run fixture materialization**

Run: `pytest tests/core1 -q`

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/core1 scripts/materialize_core1.py configs/core1 tests/core1
git commit -m "feat: materialize executable core1 noise profiles"
```

### Task 10: SkillOpt N3/N4 bridge

**Files:**
- Create: `src/rsebench/evolution/skillopt_evidence.py`
- Modify external: `methods/external/skillopt/skillopt/gradient/reflect.py`
- Create: `patches/baselines/skillopt-evidence-hook.patch`
- Test: `tests/evolution/test_skillopt_evidence.py`

**Interfaces:**
- Produces: `SkillOptEvidenceAdapter`, `mutate_skillopt_conversation`, and `mutate_skillopt_feedback_item`.
- External environment variables: `RSEBENCH_EVIDENCE_SPEC`, `RSEBENCH_EVIDENCE_AUDIT_ROOT`, `RSEBENCH_EVIDENCE_ARM`.

- [ ] **Step 1: Write failing adapter tests using native SkillOpt conversation rows**

Cover spreadsheet tool-call records, OfficeQA action/observation rows,
verification messages, identity parity, N3 omission, N4 protected-score parity,
and replay files.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/evolution/test_skillopt_evidence.py -q`

- [ ] **Step 3: Implement adapter and optional external hook**

In `fmt_minibatch_trajectories`, after loading canonical `conversation.json`,
call the RSEBench hook only when the spec environment variable is set. For N4,
copy and mutate analyst-visible `fail_reason`/verification attribution; never
rewrite `results.jsonl`, `hard`, or `soft`.

- [ ] **Step 4: Capture patch and run parity tests**

Generate the patch with `git -C $RSEBENCH_METHODS_ROOT/skillopt diff`, normalize
paths to the checkout root, and save it under `patches/baselines/`. Run:

```bash
pytest tests/evolution/test_skillopt_evidence.py tests/evolution/test_skillopt_executor.py -q
git -C "$RSEBENCH_METHODS_ROOT/skillopt" diff --check
```

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/evolution/skillopt_evidence.py tests/evolution/test_skillopt_evidence.py patches/baselines/skillopt-evidence-hook.patch
git commit -m "feat: connect skillopt evidence noise hooks"
```

### Task 11: SkillLearnBench DeepSeek round executor and hooks

**Files:**
- Create: `src/rsebench/evolution/skilllearn_executor.py`
- Create: `scripts/run_paired_skilllearn.py`
- Modify external: SkillLearnBench agent/provider and round runner files.
- Create: `patches/baselines/skilllearn-deepseek-evidence.patch`
- Test: `tests/evolution/test_skilllearn_executor.py`

**Interfaces:**
- Produces an `EvolutionExecutor` using task-family acquisition/evaluation and the standard `PairedEvolutionRunner` result contract.

- [ ] **Step 1: Write failing round-boundary tests**

Use a fake Docker environment and scripted DeepSeek responses to prove:

```text
round-1 execution -> normalized trace -> optional N3 -> reflection/teacher feedback
-> optional N4 -> skill rewrite -> clean sibling evaluation
```

Assert hidden verifier text never appears in Self-Feedback prompts, Teacher-
Feedback receives only directional failure details, and token events carry arm
and stage.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/evolution/test_skilllearn_executor.py -q`

- [ ] **Step 3: Implement DeepSeek API provider and separated rounds**

Use the existing `DeepSeekHarborAgent` for container actions and
`DeepSeekClient` for reflection/rewrite. Preserve official skill directory
layout. Run `/tests/test.sh` outside the learner boundary. Evaluate instance-2+
with the frozen final skill and official binary reward.

- [ ] **Step 4: Capture external patch and run one-family native smoke**

Run a 1 acquisition / 1 clean-test task on a low-dependency family selected by
the materializer. Require a nonempty skill, parseable trajectory, verifier
reward, audit pack, and token ledger.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/evolution/skilllearn_executor.py scripts/run_paired_skilllearn.py tests/evolution/test_skilllearn_executor.py patches/baselines/skilllearn-deepseek-evidence.patch
git commit -m "feat: add skilllearn deepseek evolution executor"
```

### Task 12: SkillAdaptor WebShop executor and hooks

**Files:**
- Create: `src/rsebench/evolution/skilladaptor_executor.py`
- Create: `scripts/run_paired_skilladaptor.py`
- Modify external: `skill-adaptor/core/orchestrator.py` and WebShop runner.
- Create: `patches/baselines/skilladaptor-evidence-hook.patch`
- Test: `tests/evolution/test_skilladaptor_executor.py`

**Interfaces:**
- N3 hook consumes native `Trajectory` before Localizer.
- N4 hook consumes native `LocalizedFault` after Localizer and before Linker.
- Produces a standard paired runner artifact by serializing the final skill bank to deterministic Markdown/JSON.

- [ ] **Step 1: Write failing native-type hook tests**

Use actual SkillAdaptor `Step`, `Trajectory`, and `LocalizedFault` imports from
the pinned checkout. Assert identity parity, N3 reward preservation, N4
`step_index/action/observation` consistency, and unchanged skill update code
when hooks are disabled.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/evolution/test_skilladaptor_executor.py -q`

- [ ] **Step 3: Implement executor and external hook**

Wrap `execute_webshop_tasks` output through `after_rollout`. Wrap the localized
fault through `after_feedback` before `_generate_candidates_for_fault`. Configure
DeepSeek's OpenAI-compatible endpoint and disable the unavailable embedding API
by using the repository's deterministic lexical matching fallback for the
pilot.

- [ ] **Step 4: Set up WebShop small data and run native smoke**

Install the pinned repositories in isolated virtual environments. Use the
official 1,000-product data path. Run 1 train / 1 validation / 2 clean-test
goals and require nonempty trajectories, valid actions, result score, mutation
audit, and token ledger.

- [ ] **Step 5: Commit**

```bash
git add src/rsebench/evolution/skilladaptor_executor.py scripts/run_paired_skilladaptor.py tests/evolution/test_skilladaptor_executor.py patches/baselines/skilladaptor-evidence-hook.patch
git commit -m "feat: add skilladaptor webshop evolution executor"
```

### Task 13: Unified 16-cell screen runner

**Files:**
- Create: `scripts/run_core1_screen.py`
- Create: `tests/test_core1_screen.py`

**Interfaces:**
- CLI accepts `--domain`, `--stage`, `--resume`, and `--smoke-only`.
- Produces one `screen_manifest.json`, per-cell run links, statuses, token totals, and `results.json`.

- [ ] **Step 1: Write failing scheduler tests**

Assert exactly 16 cells, stage-specific static/runtime materialization, clean
parity prerequisite, per-domain sizes, token cap checks before dispatch, resume
without duplicate calls, and statuses restricted to `passed|null|opposite|blocked`.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_core1_screen.py -q`

- [ ] **Step 3: Implement scheduler**

Run applicability smoke for every cell first. Dispatch efficacy only for valid
cells. Reuse one frozen split and one seed per domain. Do not regenerate N1/N2
between baselines or reruns. Persist exceptions as blocked evidence with no
fabricated score.

- [ ] **Step 4: Verify scheduler and full local suite**

Run: `pytest tests/test_core1_screen.py -q && pytest -q`

- [ ] **Step 5: Commit**

```bash
git add scripts/run_core1_screen.py tests/test_core1_screen.py
git commit -m "feat: orchestrate core1 robustness screens"
```

### Task 14: Materialize data, run smoke, then run efficacy screens

**Files:**
- Generated untracked/shared data: `benchmark/core1/` and configured output root.
- Generated reports: `outputs/runs/core1-screen/`.

**Interfaces:**
- Consumes every earlier task.
- Produces actual Core-1 noise artifacts and empirical statuses.

- [ ] **Step 1: Materialize all static artifacts and runtime specs**

Run:

```bash
python scripts/materialize_core1.py --all
```

Require 16 profiles, all static hard gates, runtime schema validation, disjoint
clean test, and no secret scan findings.

- [ ] **Step 2: Run 2-example applicability smoke for all 16 cells**

Run:

```bash
python scripts/run_core1_screen.py --smoke-only
```

Cells that fail environment/provider setup become `blocked`; do not substitute
synthetic scores.

- [ ] **Step 3: Run efficacy cells in fixed order**

Run domains in this order to bound cost and expose shared failures early:

```text
spreadsheet -> document -> skill_learning -> interactive
```

Within each domain run `N3 -> N4 -> N2 -> N1`. Use the sizes in the design
spec, one method seed `20260813`, and the profile token caps.

- [ ] **Step 4: Audit token and replay completeness**

Run:

```bash
python scripts/audit_token_usage.py
python scripts/run_core1_screen.py --audit-only
```

Require every provider call to be observable or explicitly listed as a legacy/
provider failure, and every applicable N3/N4 run to contain replay input,
output, and audit hashes.

### Task 15: Result report and final verification

**Files:**
- Create: `docs/reports/core1-validation-status.md`
- Modify: `docs/reports/current-experiment-status.md`
- Modify: `README.md`

**Interfaces:**
- Reports all 16 cells without selection bias.

- [ ] **Step 1: Generate the report from `results.json`**

For every cell include static/runtime form, applicability, seed/clean/noisy
scores, clean gain, clean-minus-noisy gap, paired interval when defined, skill
hash divergence, harmful/helpful flips, update path, token use, run path, and
status. Explain every blocked, null, and opposite cell.

- [ ] **Step 2: Run full verification**

Run fresh:

```bash
pytest -q
python -m rsebench.cli registry-check
git diff --check
git status --short
```

Also reverse-apply-check every tracked external patch against its pinned dirty
checkout and scan tracked files for API/Hugging Face token patterns.

- [ ] **Step 3: Commit reports and documentation**

```bash
git add docs/reports README.md
git commit -m "docs: report core1 hybrid noise validation"
```

- [ ] **Step 4: Invoke finishing-a-development-branch**

Present branch integration options only after all fresh verification evidence
has been read. Do not merge, push, or delete the worktree without user choice.
