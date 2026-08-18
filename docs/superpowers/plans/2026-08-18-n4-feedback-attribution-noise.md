# N4 Feedback-Attribution Noise Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement deterministic, policy-driven N4 feedback-attribution noise for Spreadsheet, OfficeQA, WebShop, and an independently versioned SkillFlow-N4 candidate, with protected-state replay and provider-free readiness reporting.

**Architecture:** Method adapters normalize native trajectory/feedback and capture protected state; benchmark policies resolve one original attribution and grounded decoys; a generic operator performs one seeded atomic replacement. `EvidenceNoiseHook` accepts an injected feedback mutator so the common evidence package does not depend on N4 benchmark plugins. Original SkillFlow remains unchanged; its N4 boundary is delivered as a candidate patch layered after the validated SkillFlow patch series.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, PyYAML, openpyxl range utilities, Git patch replay, existing RSEBench validation and provider abstractions.

## Global Constraints

- Keep all four frozen DatasetRelease manifests unchanged.
- Keep `configs/validation/validation-v1.yaml`, all active MethodRelease JSON files, clean evidence, and existing patch files byte-identical.
- Keep `methods/external/skillflow` unchanged; test the candidate patch only in a temporary checkout.
- N4 must preserve complete trajectory, reward/success, official score, final result, verifier result, and environment identity.
- N4 must not fall back to another attribution kind when its declared target is unavailable.
- Quoted OfficeQA prediction/expected values are protected and cannot be rewritten as attribution atoms.
- Clean hooks for frozen methods return the exact native object.
- Validation callers provide `application_id`; compatibility callers derive a content-addressed ID without overwriting different content.
- Every production behavior is implemented test-first: RED, GREEN, then refactor.
- No provider completion is called during this implementation or its verification.

---

### Task 1: Extend evidence contracts, adapter signatures, and replay isolation

**Files:**
- Modify: `src/rsebench/evidence/contracts.py`
- Modify: `src/rsebench/evidence/hooks.py`
- Modify: `src/rsebench/evidence/io.py`
- Modify: `src/rsebench/evidence/__init__.py`
- Modify: `src/rsebench/noise/contracts.py`
- Modify: `src/rsebench/evolution/skillopt_evidence.py`
- Modify: `src/rsebench/evolution/skilladaptor_executor.py`
- Modify: `src/rsebench/evolution/skilllearn_executor.py`
- Modify: `src/rsebench/selection/qualification_io.py`
- Modify: `tests/evidence/test_contracts.py`
- Modify: `tests/evidence/test_hooks.py`
- Modify: `tests/evolution/test_skillopt_evidence.py`
- Modify: `tests/evolution/test_skilladaptor_executor.py`
- Modify: `tests/evolution/test_skilllearn_executor.py`

**Interfaces:**
- Produces: `FeedbackRecord.blamed_skill_refs`, `FeedbackRecord.attribution_axes`.
- Produces: `ProtectedRuntimeState` and defaulted application/release fields on `HookContext`.
- Produces: `EvidenceAdapter.capture_protected_state(native_feedback, native_trajectory, context)`.
- Produces: `EvidenceNoiseHook(..., feedback_mutator=...)` and `after_feedback(..., task=None)`.
- Produces: collision-safe replay under `runtime_noise/<task>/<application>/N4/`.

- [ ] **Step 1: Write failing backward-compatibility and protected-state tests**

Add tests proving old feedback JSON receives empty new fields, the new context fields default to `None`, and invalid protected hashes are rejected:

```python
def test_old_feedback_json_gets_empty_n4_extensions() -> None:
    record = FeedbackRecord.model_validate({
        "task_id": "t1",
        "benchmark": "webshop",
        "diagnosis": "wrong step",
    })
    assert record.blamed_skill_refs == []
    assert record.attribution_axes == {}


def test_protected_runtime_state_requires_content_hashes() -> None:
    with pytest.raises(ValueError):
        ProtectedRuntimeState(
            task_identity_hash="not-a-hash",
            environment_hash="b" * 64,
            final_result_hash="c" * 64,
            official_score_hash="d" * 64,
            trajectory_hash="e" * 64,
        )
```

Update `DictAdapter` in `tests/evidence/test_hooks.py` to implement the wished-for explicit trajectory signatures and return a protected state derived from canonical hashes. Add a test with two `application_id` values and assert both replay directories exist, plus a test that an existing path with different content raises `replay identity collision`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m pytest tests/evidence/test_contracts.py tests/evidence/test_hooks.py -q
```

Expected: collection or assertion failures because the new fields, `ProtectedRuntimeState`, explicit feedback signatures, and new replay path do not exist.

- [ ] **Step 3: Add the contracts and collision-safe writer**

Add defaulted fields to `FeedbackRecord`, defaulted identity fields to `HookContext`, and:

```python
class ProtectedRuntimeState(StrictModel):
    task_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_score_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trajectory_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reward: float | None = None
    success: bool | None = None
```

Add `write_record_once(path, value)` in `evidence/io.py`: if absent, atomically write; if present with identical canonical JSON, return; if present with different canonical JSON, raise `RuntimeError("replay identity collision: ...")`.

- [ ] **Step 4: Change adapter and hook signatures**

Update both public protocols to:

```python
def normalize_feedback(self, native, native_trajectory, context) -> FeedbackRecord: ...
def denormalize_feedback(
    self, native, native_trajectory, normalized, context
): ...
def capture_protected_state(
    self, native_feedback, native_trajectory, context
) -> ProtectedRuntimeState: ...
```

Define a `FeedbackMutator` protocol accepting `(feedback, spec, trajectory, context, task)` and returning `MutationResult`. Default it to a wrapper around the existing `mutate_record`.

For N4, capture protected state before normalization and after denormalization, require exact equality, then write:

```text
input.json
output.json
audit.json
protected_state.json
token_usage.json
timing.json
```

Use `context.application_id` when present; otherwise use `auto-<input_hash[:16]>`. Keep N3 behavior compatible while migrating its replay path assertions to the same application-aware layout.

- [ ] **Step 5: Update every built-in adapter and caller atomically**

Make SkillOpt, SkillAdaptor, and `_NormalizedAdapter` accept the explicit native trajectory argument. At this contract-migration step SkillAdaptor may still retain its constructor state, but it must verify that the explicit trajectory is the same task before using it; Task 5 removes the constructor state entirely. Compute protected state from method-native immutable result fields. Update `_skillopt_task_runtime_applicability` in `selection/qualification_io.py` and every test adapter/caller in the focused suites.

- [ ] **Step 6: Run focused and compatibility tests and verify GREEN**

Run:

```bash
python -m pytest tests/evidence tests/evolution/test_skillopt_evidence.py tests/evolution/test_skilladaptor_executor.py tests/evolution/test_skilllearn_executor.py tests/selection/test_qualification.py tests/noise/test_plugin_contracts.py -q
```

Expected: all selected tests pass with zero provider calls.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/rsebench/evidence src/rsebench/noise/contracts.py src/rsebench/evolution/skillopt_evidence.py src/rsebench/evolution/skilladaptor_executor.py src/rsebench/evolution/skilllearn_executor.py src/rsebench/selection/qualification_io.py tests/evidence tests/evolution/test_skillopt_evidence.py tests/evolution/test_skilladaptor_executor.py tests/evolution/test_skilllearn_executor.py tests/noise/test_plugin_contracts.py
git commit -m "feat: strengthen N4 evidence contracts"
```

---

### Task 2: Add policy contracts and the generic policy-driven N4 operator

**Files:**
- Create: `src/rsebench/noise/stages/n4/contracts.py`
- Create: `src/rsebench/noise/stages/n4/operators/common.py`
- Modify: `src/rsebench/noise/stages/n4/operators/__init__.py`
- Create: `tests/noise/n4/test_common.py`

**Interfaces:**
- Consumes: `FeedbackRecord`, `TrajectoryRecord`, `RuntimeNoiseSpec`, `HookContext`, optional `TaskManifest`.
- Produces: `AttributionTarget`, `AttributionCandidate`, `BenchmarkN4Policy`.
- Produces: `mutate_feedback_with_policy(record, spec, trajectory, context, task, policy) -> MutationResult`.

- [ ] **Step 1: Write failing generic-operator tests**

Create a fixture policy returning one original event and two candidates. Test exact seeded determinism, budget rejection, atomic replacement of event/resource/skill/axis/diagnosis/recommendation fields, evidence-required validation, alias exclusion, and `no_grounded_decoy` identity behavior.

The central positive assertion is:

```python
result = mutate_feedback_with_policy(
    feedback, spec, trajectory, context, task, policy
)
assert result.output_record.blamed_event_ids == [selected.replacement_event_ids[0]]
assert result.output_record.blamed_resource_refs == selected.replacement_resource_refs
assert result.output_record.blamed_skill_refs == selected.replacement_skill_refs
assert result.output_record.attribution_axes == selected.replacement_axes
assert result.output_record.scalar_reward == feedback.scalar_reward
assert result.audit.metadata["eligible_candidate_ids"] == ["c1", "c2"]
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
python -m pytest tests/noise/n4/test_common.py -q
```

Expected: import failure for `rsebench.noise.stages.n4.contracts`.

- [ ] **Step 3: Implement typed targets, candidates, and policy protocol**

Use frozen Pydantic models with non-empty `candidate_id`, a literal kind of `event|resource|skill|axis`, defaulted replacement lists/maps, non-empty `evidence_refs`, and a policy protocol with `resolve_original` and `resolve_decoys` methods matching the approved design.

- [ ] **Step 4: Implement deterministic atomic replacement**

Rank candidates using:

```python
sha256(
    f"{spec.seed}:{record.task_id}:{context.application_id or ''}:"
    f"{candidate.candidate_id}".encode("utf-8")
).hexdigest()
```

Reject candidates that equal the canonical original target or have no evidence. Construct `MutationAudit` directly with stable reason codes and include original target, eligible IDs, policy name/version, and candidate evidence in metadata. Do not modify the legacy `same_kind_decoy_event` and `same_shape_decoy_resource` paths.

- [ ] **Step 5: Run generic and legacy operator tests and verify GREEN**

Run:

```bash
python -m pytest tests/noise/n4/test_common.py tests/evidence/test_operators.py -q
```

Expected: all tests pass and legacy N3/N4 selectors remain deterministic.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/rsebench/noise/stages/n4 tests/noise/n4/test_common.py
git commit -m "feat: add policy-driven N4 mutation"
```

---

### Task 3: Extract adapters and implement Spreadsheet N4

**Files:**
- Create: `src/rsebench/evidence/adapters/__init__.py`
- Create: `src/rsebench/evidence/adapters/skillopt.py`
- Modify: `src/rsebench/evolution/skillopt_evidence.py`
- Create: `src/rsebench/noise/stages/n4/operators/spreadsheet.py`
- Create: `tests/noise/n4/test_spreadsheet.py`
- Modify: `tests/evolution/test_skillopt_evidence.py`

**Interfaces:**
- Produces: `SkillOptEvidenceAdapter` in the canonical adapter package, re-exported by the old evolution module.
- Produces: `SpreadsheetN4Policy` with `policy_name="spreadsheet"`, `version="v1"`.
- Produces: policy dispatch for `spreadsheet_n4_replace_blamed_range`.

- [ ] **Step 1: Write failing Spreadsheet policy tests**

Cover:

```python
feedback = FeedbackRecord(
    task_id="sheet-1",
    benchmark="spreadsheetbench_verified",
    blamed_resource_refs=["'Result'!B3"],
    diagnosis="eval-mismatch: value@'Result'!B3: gt='x' pred='y'",
    scalar_reward=0.0,
)
```

Use trajectory refs `Result!B3`, `Archive!F8`, and `Archive!F8:G8`. Assert the canonical alias is excluded, the 1x1 decoy is selected, the 1x2 ref is excluded, and only the range fragment changes. Add RED cases for `exec-error`, empty feedback, protected events, and no same-shape decoy.

- [ ] **Step 2: Run Spreadsheet tests and verify RED**

Run:

```bash
python -m pytest tests/noise/n4/test_spreadsheet.py tests/evolution/test_skillopt_evidence.py -q
```

Expected: missing policy module and old adapter signature failures.

- [ ] **Step 3: Extract the SkillOpt adapter without breaking the external hook**

Move normalization helpers and `SkillOptEvidenceAdapter` into `evidence/adapters/skillopt.py`. Keep `mutate_skillopt_conversation`, `mutate_skillopt_feedback_item`, `_enrich_n3_spec`, `_enrich_n4_spec`, and `apply_skillopt_evidence_from_env` in the evolution compatibility module. Re-export the class so the validated SkillOpt patch import remains valid.

Implement `capture_protected_state` using:

- task hash from task/benchmark/release identity;
- trajectory hash from normalized conversation;
- final-result hash from native fields excluding `fail_reason` and other authorized attribution fields;
- official-score hash from `hard`, `soft`, `exact`, and `score_rationale` when present;
- reward from numeric `soft` and success from numeric `hard`;
- environment hash from context metadata or the canonical null sentinel.

- [ ] **Step 4: Implement canonical range policy and hook dispatch**

Normalize quoted sheet aliases, compute range shape with `range_boundaries`, preserve the exact `gt=... pred=...` suffix, and build one candidate per real same-shape event resource. In `mutate_skillopt_feedback_item`, resolve the N4 registration by operator and inject its mutator; retain the legacy mutator for unregistered specs.

- [ ] **Step 5: Run Spreadsheet and SkillOpt tests and verify GREEN**

Run:

```bash
python -m pytest tests/noise/n4/test_spreadsheet.py tests/evolution/test_skillopt_evidence.py tests/selection/test_qualification.py -q
```

Expected: all tests pass; clean path preserves object identity; N4 replay contains the six required files.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/rsebench/evidence/adapters src/rsebench/evolution/skillopt_evidence.py src/rsebench/noise/stages/n4/operators/spreadsheet.py tests/noise/n4/test_spreadsheet.py tests/evolution/test_skillopt_evidence.py
git commit -m "feat: add Spreadsheet attribution noise"
```

---

### Task 4: Implement strict OfficeQA N4 without answer corruption

**Files:**
- Create: `src/rsebench/noise/stages/n4/operators/officeqa.py`
- Create: `tests/noise/n4/test_officeqa.py`
- Modify: `src/rsebench/evolution/skillopt_evidence.py`
- Modify: `tests/evolution/test_skillopt_evidence.py`

**Interfaces:**
- Produces: `OfficeQAN4Policy` with axes `source|period|unit|aggregation`.
- Produces: stable `unparseable_original_attribution` and `ambiguous_original_attribution` audits.

- [ ] **Step 1: Write failing strict-boundary tests**

Test that this message is inapplicable and byte-identical:

```python
"predicted '17.09 to 18.91 billion dollars' but expected '1.81'"
```

Test a standalone source diagnosis such as `Wrong source: treasury_1942_04.txt` with a real decoy source-read event. Test a standalone period diagnosis with two periods present in non-quoted trajectory text. Test that multiple standalone axes produce `ambiguous_original_attribution`, and that gold document IDs never occur in the rendered output or audit fragments.

- [ ] **Step 2: Run OfficeQA tests and verify RED**

Run:

```bash
python -m pytest tests/noise/n4/test_officeqa.py -q
```

Expected: import failure for the OfficeQA policy.

- [ ] **Step 3: Implement quote masking and axis resolution**

Replace single- and double-quoted spans with equal-length spaces before scanning. Resolve exactly one standalone axis. For source decoys require a real trajectory resource; for period/unit/aggregation require the replacement token to occur in non-quoted learner-visible prompt/trajectory evidence. The replacement diagnosis changes only the resolved span.

- [ ] **Step 4: Add OfficeQA dispatch and provider-free coverage fixture**

Register `officeqa_n4_replace_failure_axis` for the frozen SkillOpt OfficeQA release, but mark its frozen-evidence coverage probe false when the only tokens are inside quoted prediction/expected spans. The policy implementation remains available for explicit standalone-attribution fixtures.

- [ ] **Step 5: Run OfficeQA, SkillOpt, and scoring tests and verify GREEN**

Run:

```bash
python -m pytest tests/noise/n4/test_officeqa.py tests/evolution/test_skillopt_evidence.py tests/evolution/test_skillopt_officeqa_runtime.py tests/domains/test_officeqa_scoring.py -q
```

Expected: all tests pass; no quoted prediction/expected content changes.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/rsebench/noise/stages/n4/operators/officeqa.py src/rsebench/evolution/skillopt_evidence.py tests/noise/n4/test_officeqa.py tests/evolution/test_skillopt_evidence.py
git commit -m "feat: add strict OfficeQA attribution noise"
```

---

### Task 5: Extract the SkillAdaptor adapter and implement coherent WebShop N4

**Files:**
- Create: `src/rsebench/evidence/adapters/skilladaptor.py`
- Modify: `src/rsebench/evidence/adapters/__init__.py`
- Modify: `src/rsebench/evolution/skilladaptor_executor.py`
- Create: `src/rsebench/noise/stages/n4/operators/webshop.py`
- Create: `tests/noise/n4/test_webshop.py`
- Modify: `tests/evolution/test_skilladaptor_executor.py`

**Interfaces:**
- Produces: stateless `SkillAdaptorEvidenceAdapter` with explicit trajectory arguments.
- Produces: `WebShopN4Policy` with action classes `search`, `navigation`, `option`, and `purchase`.

- [ ] **Step 1: Write failing stateless-adapter and same-class tests**

Instantiate `SkillAdaptorEvidenceAdapter()` without constructor state. Normalize and restore a fault by passing the trajectory explicitly. Use a trajectory with two option-selection actions and one purchase action; blame one option action and assert the other option action is eligible while purchase is not. Add a no-same-class identity case.

- [ ] **Step 2: Run WebShop tests and verify RED**

Run:

```bash
python -m pytest tests/noise/n4/test_webshop.py tests/evolution/test_skilladaptor_executor.py -q
```

Expected: constructor/signature failures and missing WebShop policy.

- [ ] **Step 3: Extract and make the adapter stateless**

Move `SkillAdaptorEvidenceAdapter` and action parsing helpers to the canonical adapter package. Remove `_require_trajectory`; every feedback method uses its explicit `native_trajectory`. Store `action_class` in normalized event metadata. Re-export the class from `skilladaptor_executor.py` for current imports.

Implement protected state solely from immutable trajectory/outcome fields and context identity, excluding mutable `LocalizedFault` attribution fields.

- [ ] **Step 4: Implement coherent WebShop candidates**

Build candidates only from events with the same `action_class`. Candidate diagnosis is:

```text
The first actionable fault is attributed to <event-id>: <action>.
```

The existing adapter denormalizer must synchronize `step_index`, observation, wrong action, skills at fault, fault chain, and improvement principle from the selected step.

- [ ] **Step 5: Run WebShop and executor tests and verify GREEN**

Run:

```bash
python -m pytest tests/noise/n4/test_webshop.py tests/evolution/test_skilladaptor_executor.py -q
```

Expected: all tests pass, including owned evidence persistence and external hook compatibility.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/rsebench/evidence/adapters src/rsebench/evolution/skilladaptor_executor.py src/rsebench/noise/stages/n4/operators/webshop.py tests/noise/n4/test_webshop.py tests/evolution/test_skilladaptor_executor.py
git commit -m "feat: add coherent WebShop attribution noise"
```

---

### Task 6: Implement the RSEBench-side SkillFlow attribution bridge

**Files:**
- Create: `src/rsebench/evidence/adapters/skillflow.py`
- Modify: `src/rsebench/evidence/adapters/__init__.py`
- Create: `src/rsebench/evolution/skillflow_n4.py`
- Create: `src/rsebench/noise/stages/n4/operators/skillflow.py`
- Create: `tests/noise/n4/test_skillflow.py`
- Create: `tests/evolution/test_skillflow_n4.py`

**Interfaces:**
- Produces: `SkillFlowAttributionPayload` strict analyzer schema.
- Produces: `SkillFlowEvidenceAdapter` for `TrialOutcome`-shaped mappings and analyzer feedback.
- Produces: `SkillFlowAttributionAnalyzer(client).analyze(outcome, snapshot, context) -> FeedbackRecord`.
- Produces: `build_skillflow_feedback_from_env(...) -> FeedbackRecord` for the candidate patch.
- Produces: `render_skillflow_feedback(feedback) -> str`.

- [ ] **Step 1: Write failing analyzer and policy tests**

Use a fake client that returns strict JSON, not a provider mock. Assert the analyzer rejects unknown event IDs, skill refs absent from snapshot/read evidence, patch keys such as `upsert_files`, and non-object JSON. Assert a valid failure and a valid `success_lesson` normalize correctly.

For policy tests, create two same-class events and two existing skill paths. Assert a grounded decoy changes either the event or skill attribution, while `TrialOutcome`, reward, verifier status, failed tests, and trajectory hashes remain identical.

- [ ] **Step 2: Run SkillFlow bridge tests and verify RED**

Run:

```bash
python -m pytest tests/noise/n4/test_skillflow.py tests/evolution/test_skillflow_n4.py -q
```

Expected: missing adapter, bridge, and policy modules.

- [ ] **Step 3: Implement strict parsing and normalized trajectory IDs**

Create stable event IDs `trial-step-<native-index>`, classify events by their explicit type/tool/action fields, and record real resource/skill refs. Validate analyzer payload with `extra="forbid"`; reject any patch-operation key before constructing `FeedbackRecord`.

- [ ] **Step 4: Implement analyzer with injected client and environment factory**

The system prompt requires only diagnosis and recommendation JSON. Call:

```python
response = client.complete(
    messages,
    response_format={"type": "json_object"},
    role="skillflow_n4_attribution",
)
```

The environment factory creates the existing locked DeepSeek client only when actually called by the candidate method. Tests inject a fake client and monkeypatch `DeepSeekClient.complete` to fail if provider-free paths instantiate it. Record analyzer token/timing data through existing token context and a dedicated timing JSON.

- [ ] **Step 5: Implement SkillFlow same-class policy and renderer**

Candidates must cite real event IDs or snapshot skill paths. Render a dedicated `## Structured attribution feedback` JSON block that contains no patch operations. Clean arm returns the validated analyzer feedback; noisy arm applies the N4 hook before rendering.

- [ ] **Step 6: Run SkillFlow bridge tests and verify GREEN**

Run:

```bash
python -m pytest tests/noise/n4/test_skillflow.py tests/evolution/test_skillflow_n4.py -q
```

Expected: all tests pass and provider call counter remains zero.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/rsebench/evidence/adapters/skillflow.py src/rsebench/evolution/skillflow_n4.py src/rsebench/noise/stages/n4/operators/skillflow.py tests/noise/n4/test_skillflow.py tests/evolution/test_skillflow_n4.py
git commit -m "feat: add SkillFlow N4 attribution bridge"
```

---

### Task 7: Create the independent SkillFlow-N4 candidate patch

**Files:**
- Create: `methods/candidates/skillflow_n4/method.yaml`
- Create: `methods/candidates/skillflow_n4/patches/series.yaml`
- Create: `methods/candidates/skillflow_n4/patches/skillflow-n4-attribution-boundary.patch`
- Create: `methods/candidates/skillflow_n4/integration/provider-free-readiness.json`
- Create: `tests/skillflow/test_n4_candidate_patch.py`
- Modify: `tests/methods/test_catalog.py`

**Interfaces:**
- Consumes: `build_skillflow_feedback_from_env` and `render_skillflow_feedback` from Task 6.
- Produces: candidate method identity `skillflow_n4` with no active release.
- Produces: a patch applied after the original validated SkillFlow patch series.

- [ ] **Step 1: Write failing candidate identity and patch-replay tests**

Test that the catalog reports `skillflow_n4` as candidate and still reports exactly the same four active releases/fingerprints. In a temporary checkout:

1. archive upstream revision `7b49ff5a7e26cd7706e959bfa0dba4746d18440d`;
2. initialize a temporary Git repository;
3. apply every original patch from `methods/validated/skillflow/patches/series.yaml`;
4. apply the candidate patch;
5. compile the patched `patcher.py` and runner;
6. assert the runner calls the attribution bridge before `generate_patch`;
7. assert `_build_user_prompt` accepts and renders the structured feedback.

Also hash all original SkillFlow release and patch files before/after the test and assert equality.

- [ ] **Step 2: Run candidate tests and verify RED**

Run:

```bash
python -m pytest tests/skillflow/test_n4_candidate_patch.py tests/methods/test_catalog.py -q
```

Expected: candidate metadata and patch files are missing.

- [ ] **Step 3: Add candidate metadata**

Create `method.yaml` with:

```yaml
schema_version: rsebench.method.v1
method: skillflow_n4
status: candidate
upstream_repository: https://github.com/ZhangZi-a/SkillFlow.git
upstream_revision: 7b49ff5a7e26cd7706e959bfa0dba4746d18440d
code_status: provider_free_boundary_validated
local_checkout: skillflow
releases: []
```

The candidate series references the validated base series and records the candidate patch SHA-256. It does not create a MethodRelease JSON.

- [ ] **Step 4: Author the candidate patch against the fully patched temporary tree**

Patch `libs/skill_evolution/patcher.py` so `_build_user_prompt` and `generate_patch` accept a required `feedback_text` argument and insert it under `## Structured attribution feedback`. Patch `iterative_shared_skills_runner.py` so the operation order is exactly:

```python
feedback = build_skillflow_feedback_from_env(
    outcome=outcome.__dict__,
    snapshot=snapshot,
    task_id=task_name,
    run_dir=debug_dir,
)
feedback_text = render_skillflow_feedback(feedback)
patch = evolver.generate_patch(snapshot, outcome, feedback_text=feedback_text)
```

Persist `feedback.json` next to `outcome.json` and `patch.json`. Do not alter verifier, reward, trajectory, or patch application code.

- [ ] **Step 5: Add readiness evidence and verify patch replay GREEN**

Record original release fingerprint, original patch-series hash, candidate patch hash, provider calls `0`, and the exact provider-free test command in `provider-free-readiness.json`.

Run:

```bash
python -m pytest tests/skillflow/test_n4_candidate_patch.py tests/methods/test_catalog.py tests/skillflow/test_patch_observability.py -q
```

Expected: patch applies after the original series; original files remain byte-identical; all tests pass.

- [ ] **Step 6: Commit Task 7**

```bash
git add methods/candidates/skillflow_n4 tests/skillflow/test_n4_candidate_patch.py tests/methods/test_catalog.py
git commit -m "feat: add independent SkillFlow N4 candidate"
```

---

### Task 8: Add N4 registrations, applicability audit, and truthful validation readiness

**Files:**
- Create: `src/rsebench/noise/stages/n4/registry.py`
- Modify: `src/rsebench/noise/stages/n4/operators/__init__.py`
- Modify: `src/rsebench/validation/service.py`
- Create: `scripts/audit_n4_applicability.py`
- Create: `tests/noise/n4/test_registry.py`
- Modify: `tests/validation/test_validation_preflight.py`
- Create: `tests/validation/test_n4_applicability_audit.py`

**Interfaces:**
- Produces: frozen `N4Registration` and `N4_REGISTRATIONS` keyed by operator.
- Produces: readiness states `interface_only|implemented|method_release_incompatible|insufficient_attribution_coverage|execution_ready`.
- Produces: provider-free JSON applicability report with fixed denominator and reason counts.

- [ ] **Step 1: Write failing registry and preflight tests**

Assert exact registrations for all four operator IDs. Assert:

- Spreadsheet frozen release: `implemented` until a provider-backed runner is registered;
- OfficeQA frozen release: `insufficient_attribution_coverage` for the frozen clean fixture;
- WebShop frozen release: `implemented` until a provider-backed runner is registered;
- original SkillFlow release: `method_release_incompatible`;
- all N1-N3 cells remain `interface_only`;
- overall `execution_ready` remains false;
- provider calls remain zero.

Keep the existing structural `ready_cell_count == 16` and add `execution_ready_cell_count` rather than changing its meaning.

- [ ] **Step 2: Run registry/preflight tests and verify RED**

Run:

```bash
python -m pytest tests/noise/n4/test_registry.py tests/validation/test_validation_preflight.py tests/validation/test_n4_applicability_audit.py -q
```

Expected: missing registry and readiness fields.

- [ ] **Step 3: Implement registrations without fake cell runners**

Each registration declares operator, adapter name, policy object, supported method release IDs, fixture applicability, and optional runner. `CELL_RUNNERS` contains only registrations whose runner is callable. Do not register a provider-free fixture function as a validation cell runner.

- [ ] **Step 4: Teach preflight to inspect registrations**

For N4, load `N4_REGISTRATIONS` and evaluate implementation, release compatibility, fixture coverage, and runner presence separately. For N1-N3 preserve current callable-based behavior. Return both the existing `operator_implementations` mapping and a new `cell_readiness` mapping with reasons.

- [ ] **Step 5: Implement the provider-free applicability audit CLI**

The script accepts repeated `--evidence-root`, `--matrix`, and `--output`. It reads owned normalized/native evidence where present, runs the registered policy/operator without constructing a provider client, and writes:

```json
{
  "schema_version": "rsebench.n4-applicability-report.v1",
  "fixed_denominator": 4,
  "feedback_bearing_count": 4,
  "applicable_count": 0,
  "inapplicable_reason_counts": {"unparseable_original_attribution": 4},
  "provider_calls": 0
}
```

Use real counts from inputs; the values above are the OfficeQA fixture expectation.

- [ ] **Step 6: Run readiness tests and verify GREEN**

Run:

```bash
python -m pytest tests/noise/n4/test_registry.py tests/validation/test_validation_preflight.py tests/validation/test_n4_applicability_audit.py -q
```

Expected: all pass; no validation runner or provider client is invoked.

- [ ] **Step 7: Commit Task 8**

```bash
git add src/rsebench/noise/stages/n4 src/rsebench/validation/service.py scripts/audit_n4_applicability.py tests/noise/n4/test_registry.py tests/validation/test_validation_preflight.py tests/validation/test_n4_applicability_audit.py
git commit -m "feat: report truthful N4 readiness"
```

---

### Task 9: Complete provider-free verification and update N4 status

**Files:**
- Modify: `docs/progress/n4-update-feedback.md`
- Create: `docs/reports/current/2026-08-18-n4-provider-free-readiness.md`
- Modify: `tests/validation/test_validation_release_audit.py`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: an evidence-backed status report that separates implemented logic from formal paid-cell readiness.

- [ ] **Step 1: Write the failing documentation assertions**

Add assertions that the N4 progress page names all five readiness states, links the design and implementation plan, records provider calls `0`, and explicitly states that original SkillFlow is unchanged and formal SkillFlow N4 waits for a new clean release.

- [ ] **Step 2: Run the documentation test and verify RED**

Run:

```bash
python -m pytest tests/validation/test_validation_release_audit.py -q
```

Expected: missing readiness report/link assertions.

- [ ] **Step 3: Update progress and readiness documentation**

Record per-domain logic status, applicability status, release compatibility, runner status, protected-state tests, patch-replay result, provider calls/tokens/time, and the exact commands executed. Do not mark a cell execution-ready when it lacks a provider-backed runner, applicable frozen evidence, or compatible MethodRelease.

- [ ] **Step 4: Run targeted N4 verification**

Run:

```bash
python -m pytest tests/evidence tests/noise/n4 tests/evolution/test_skillopt_evidence.py tests/evolution/test_skilladaptor_executor.py tests/evolution/test_skillflow_n4.py tests/skillflow/test_n4_candidate_patch.py tests/validation/test_validation_preflight.py tests/validation/test_n4_applicability_audit.py -q
```

Expected: all tests pass with zero provider calls.

- [ ] **Step 5: Run regression suites**

Run:

```bash
python -m pytest tests/noise tests/evidence tests/evolution tests/methods tests/skillflow tests/validation -q
```

Expected: all tests pass. Environment-dependent native tests may be skipped only by their existing explicit skip markers.

- [ ] **Step 6: Verify frozen identity and clean diff**

Run:

```bash
git diff 974ff6d -- configs/validation/validation-v1.yaml benchmark/datasets methods/validated/skillflow methods/validated/skillopt/releases methods/validated/skilladaptor/releases
git diff --check
git status --short
```

Expected: no diff for frozen paths; no whitespace errors; only intentional implementation/report files are modified before the final commit.

- [ ] **Step 7: Commit Task 9**

```bash
git add docs/progress/n4-update-feedback.md docs/reports/current/2026-08-18-n4-provider-free-readiness.md tests/validation/test_validation_release_audit.py
git commit -m "docs: record N4 provider-free readiness"
```

- [ ] **Step 8: Final verification summary**

Report exact test counts, skips, provider calls, per-domain readiness state, commit list, and remaining scientific blockers. Do not run `rsebench validation run` or pass `--confirm-provider-cost` in this implementation phase.
