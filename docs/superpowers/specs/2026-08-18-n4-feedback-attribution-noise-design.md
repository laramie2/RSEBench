# N4 feedback-attribution noise design

> **Superseded for current N4 semantics (2026-08-21).** 本文保留旧 feedback-attribution 方案作为历史设计记录，不应继续据此实现 N4。最新版定义是 updater 消费前的 outcome→evidence misbinding，见 [N4 Update-Evidence Misbinding 交接方案](../../architecture/2026-08-21-n4-update-evidence-misbinding-handoff.md)。

## 1. Goal

Implement validation-v1 N4 as deterministic, auditable corruption of the
learner-visible attribution produced after execution and before a method
updates its skill state. The implementation must reuse the reserved N1-N4
plugin/runtime boundary, preserve the frozen datasets and active clean
baseline releases, and leave an extension point for future methods and
benchmarks.

The four frozen operator identities remain:

| Domain | Benchmark | Method | Operator |
|---|---|---|---|
| spreadsheet | SpreadsheetBench-Verified | SkillOpt | `spreadsheet_n4_replace_blamed_range` |
| document | OfficeQA Full | SkillOpt | `officeqa_n4_replace_failure_axis` |
| interactive | WebShop | SkillAdaptor | `webshop_n4_replace_fault_step` |
| skill | SkillFlow Tasks | SkillFlow-N4 variant | `skillflow_n4_replace_patch_attribution` |

The implementation is complete only when it can show which attribution was
changed, why the decoy was eligible, and that trajectory, reward, official
score, final result, and environment identity were not changed.

## 2. Non-goals

N4 does not:

- modify a rollout trajectory;
- change a reward, verifier result, official score, final answer, or artifact;
- edit a generated skill patch after the updater has produced it;
- combine with N3 in the same experimental arm;
- invent a fallback mutation merely to increase applicability;
- rewrite frozen DatasetRelease, MethodRelease, matrix, or clean-evidence artifacts;
- treat an unsupported feedback boundary as evidence of robustness.

Provider-backed validation is not part of the first implementation pass. The
first pass ends with provider-free contract, fixture, patch-replay, frozen
identity, and readiness verification. Paid execution is a separate gate.

## 3. Evidence behind the design

The active methods expose three different update shapes:

- SkillOpt renders `fail_reason` and the stored trajectory to its reflection
  model. Spreadsheet failures frequently contain a concrete cell/range.
  OfficeQA failures usually contain only predicted/expected values.
- SkillAdaptor already creates a structured `LocalizedFault` before linking
  and revising skills. This is the clearest native N4 boundary.
- SkillFlow currently builds a `TrialOutcome` and immediately asks one patcher
  call to both diagnose the outcome and generate a patch. It has no independent
  attribution object.

The validated-inactive SkillLearn integration and the candidate SkillGrad,
Trace2Skill, and RethinkSkill methods all use a diagnosis/feedback-to-update
shape. They support a common `FeedbackRecord` boundary without requiring a
method-specific N4 operator.

Inspection of the frozen OfficeQA clean evolution evidence found four failed
rollouts in the selected run, all with generic predicted/expected mismatch
messages. One message contained a unit word, but it was inside the quoted
prediction and is therefore part of protected final-answer evidence, not a
standalone attribution atom. The frozen OfficeQA release must consequently be
expected to have low or zero strict N4 applicability rather than being given a
fabricated diagnosis.

## 4. Architecture

N4 is split into three layers:

```text
native feedback + read-only native trajectory
    -> MethodFeedbackAdapter
    -> FeedbackRecord + TrajectoryRecord
    -> BenchmarkN4Policy
    -> AttributionCandidate set
    -> GenericN4AttributionOperator
    -> protected-state audit + replay pack
    -> MethodFeedbackAdapter
    -> native updater input
```

The responsibilities are deliberately separate:

| Layer | Responsibility | Method-specific | Benchmark-specific |
|---|---|---:|---:|
| Method adapter | Capture and restore native feedback/trajectory | yes | no |
| Benchmark policy | Resolve original attribution and grounded decoys | no | yes |
| Generic operator | Select one decoy, replace the attribution bundle, audit | no | no |

The initial code layout is:

```text
src/rsebench/evidence/
├── contracts.py
├── hooks.py
└── adapters/
    ├── skillopt.py
    ├── skilladaptor.py
    ├── skillflow.py
    └── skilllearn.py

src/rsebench/noise/stages/n4/
├── contracts.py
├── registry.py
└── operators/
    ├── common.py
    ├── spreadsheet.py
    ├── officeqa.py
    ├── webshop.py
    └── skillflow.py
```

Existing import paths under `rsebench.evolution` may re-export adapters during
the migration, but there must be one implementation of each method adapter.

## 5. Runtime contracts

### 5.1 FeedbackRecord

`FeedbackRecord` retains its existing fields and adds defaulted fields so old
serialized records remain valid:

```python
class FeedbackRecord:
    task_id: str
    benchmark: str
    blamed_event_ids: list[str]
    blamed_resource_refs: list[str]
    blamed_skill_refs: list[str]
    attribution_axes: dict[str, str]
    diagnosis: str
    recommendation: str
    scalar_reward: float | None
    metadata: dict[str, Any]
```

`attribution_axes` contains only learner-visible attribution values such as
`source`, `period`, `unit`, or `aggregation`. Gold-only values cannot be placed
in this mapping.

### 5.2 AttributionCandidate

The policy returns typed candidates rather than partially mutated feedback:

```python
class AttributionCandidate:
    candidate_id: str
    kind: Literal["event", "resource", "skill", "axis"]
    replacement_event_ids: list[str]
    replacement_resource_refs: list[str]
    replacement_skill_refs: list[str]
    replacement_axes: dict[str, str]
    replacement_diagnosis: str
    replacement_recommendation: str | None
    evidence_refs: list[str]
```

Every candidate must cite real trajectory, prompt, resource, or skill-library
evidence. A candidate without evidence is invalid rather than inapplicable.

### 5.3 BenchmarkN4Policy

Each domain implements:

```python
class BenchmarkN4Policy(Protocol):
    def resolve_original(
        self,
        feedback: FeedbackRecord,
        trajectory: TrajectoryRecord,
        task: TaskManifest,
        context: HookContext,
    ) -> AttributionTarget | None: ...

    def resolve_decoys(
        self,
        original: AttributionTarget,
        feedback: FeedbackRecord,
        trajectory: TrajectoryRecord,
        task: TaskManifest,
        context: HookContext,
    ) -> list[AttributionCandidate]: ...
```

Policies may read benchmark-owned gold metadata to exclude invalid candidates
or audit the selection. They must not render that metadata into learner-visible
feedback.

### 5.4 Adapter boundary

Feedback normalization and restoration explicitly receive the matching
trajectory:

```python
normalize_feedback(native_feedback, native_trajectory, context)
denormalize_feedback(
    native_feedback,
    native_trajectory,
    normalized_feedback,
    context,
)
```

This replaces the stateful SkillAdaptor pattern that stores a trajectory in an
adapter constructor and could accidentally associate feedback with another
task. SkillOpt, SkillAdaptor, SkillLearn compatibility code, and all test
adapters are updated together.

### 5.5 HookContext and application identity

`HookContext` adds defaulted execution identity fields:

```python
attempt_id: str | None
application_id: str | None
sequence_index: int | None
dataset_release_id: str | None
method_release_id: str | None
replicate_id: str | None
```

Validation runners must provide an explicit unique `application_id`. Legacy
callers may derive a deterministic ID from the immutable context and invocation
index, but replay writes must never silently overwrite an existing application.

### 5.6 ProtectedRuntimeState

The adapter or runner captures:

```python
class ProtectedRuntimeState:
    task_identity_hash: str
    environment_hash: str
    final_result_hash: str
    official_score_hash: str
    trajectory_hash: str
    reward: float | None
    success: bool | None
```

For N4 every field must be identical before and after normalization, mutation,
and restoration. A mismatch is a hard failure and the updater does not receive
the mutated object.

## 6. Generic mutation semantics

The common operator:

1. validates N4 stage, task identity, and mutation budget `1`;
2. asks the policy to resolve exactly one original attribution target;
3. validates and canonicalizes the policy's candidate set;
4. excludes aliases of the original target and protected candidates;
5. selects one candidate by a stable hash of seed, task, application, and candidate identity;
6. atomically replaces the complete attribution bundle;
7. preserves scalar reward and all protected runtime state;
8. records input, output, selection evidence, and applicability.

The operator never falls back from one selector or attribution kind to another.
Re-running the same application with the same input and seed must produce the
same output and audit selection.

Canonical resource identity includes aliases such as quoted/unquoted worksheet
names and full-path/basename document references. An alias of the original
resource cannot be selected as a decoy.

## 7. Domain policies

### 7.1 SpreadsheetBench-Verified

The policy accepts only a parseable `eval-mismatch` with a canonical worksheet
and cell/range attribution. It rejects empty feedback, execution errors, output
missing errors, and malformed locations.

Decoys must:

- occur in the real trajectory;
- have the same row-by-column shape as the original range;
- resolve to a different canonical resource;
- not be protected user/system context;
- not alias the original answer location.

The mutation synchronizes event IDs, resource refs, and the location fragment
in the diagnosis. Ground-truth and predicted payloads in the failure message
remain byte-identical.

### 7.2 OfficeQA Full

The frozen SkillOpt release uses strict native-replacement mode. The policy may
replace only a standalone learner-visible attribution atom in one of:

- `source`;
- `period`;
- `unit`;
- `aggregation`.

Quoted prediction and expected-answer spans are protected and cannot be used as
attribution atoms or rewritten. A decoy must be supported by the task prompt,
trajectory, or a real accessed resource. Gold document IDs and gold answers may
be used only to reject a candidate and in non-rendered audit hashes.

If no standalone atom exists, or more than one interpretation remains, the
result is inapplicable. The implementation must report the resulting low
coverage honestly.

If later validation requires broader coverage, it requires a separate
attribution-enabled SkillOpt OfficeQA method release. That variant must add the
same structured attribution boundary to clean and noisy arms and obtain a new
clean control; it cannot be folded into `skillopt-officeqa-validation-v1`.

### 7.3 WebShop

The original attribution is the native `LocalizedFault.step_index`. Candidates
must be real trajectory actions of the same action class, excluding the
original fault and protected terminal state. Action classes distinguish at
least search/query refinement, navigation/product click, option selection, and
purchase/termination.

The adapter replaces the coherent native bundle:

- `step_index`;
- `observation`;
- `wrong_action`;
- `skills_at_fault`;
- `fault_chain`;
- `improvement_principle`.

Changing only the numeric step while retaining text about the original fault
is invalid. With no same-class decoy, the application is inapplicable.

### 7.4 SkillFlow Tasks

Original SkillFlow has no feedback-attribution boundary. The N4-capable method
variant introduces:

```text
TrialOutcome
    -> Attribution Analyzer
    -> validated FeedbackRecord
    -> N4 hook
    -> feedback section in patcher prompt
    -> patch generation
```

The analyzer emits strict JSON containing:

```json
{
  "category": "failure | success_lesson",
  "blamed_event_ids": ["event-id"],
  "blamed_skill_refs": ["skill/path"],
  "diagnosis": "...",
  "recommendation": "..."
}
```

Event IDs must exist in the original trajectory. Skill refs must exist in the
skill snapshot or actual skill read/use evidence. The analyzer cannot emit
upsert/delete operations or any other patch instruction.

N4 selects a real same-class event or skill path that is not the original
target. With no grounded decoy the application is inapplicable. Trajectory,
verifier failures, reward, and `TrialOutcome` are immutable.

The analyzer is a fixed part of the modified method and therefore executes in
both its clean and noisy arms. Its tokens and timing are separately recorded.
Provider-free tests use a fixture/stub analyzer.

## 8. SkillFlow version separation

The active original assets remain unchanged:

```text
methods/validated/skillflow/
methods/external/skillflow/
```

The implementation adds:

```text
methods/candidates/skillflow_n4/
├── method.yaml
├── patches/
│   ├── series.yaml
│   └── skillflow-n4-attribution-boundary.patch
└── integration/
    └── provider-free-readiness.json
```

The new patch is tested by applying the original SkillFlow validation patch
series and then the candidate patch to a temporary checkout. No patch is
applied in place to `methods/external/skillflow`, and no existing release JSON,
fingerprint, clean evidence, or patch hash is changed.

The candidate method identity is `skillflow_n4`. A future formal release may be
named `skillflow-n4-attribution-validation-v1`, but it can be created only after
the modified clean arm has run successfully and its clean evidence has been
frozen.

The current `validation-v1` matrix continues to reference
`skillflow-validation-v1`; it must not silently switch to the candidate method.

## 9. Registration and readiness

N4 registrations bind an operator to an adapter, policy, supported method
releases, runtime-spec builder, and runner:

```python
N4Registration(
    operator="webshop_n4_replace_fault_step",
    adapter="skilladaptor",
    policy="webshop",
    supported_method_releases={"skilladaptor-webshop-validation-v1"},
    runner=run_webshop_n4_cell,
)
```

Adding a baseline requires an adapter plus registration; adding a benchmark
requires a policy plus registration. The generic operator contains no
baseline/benchmark conditionals.

Preflight must distinguish at least:

- `interface_only` — no implementation;
- `implemented` — code and provider-free fixtures exist;
- `method_release_incompatible` — implementation requires another release;
- `insufficient_attribution_coverage` — strict fixtures contain no applicable mutation;
- `execution_ready` — all compatibility, fixture, protected-state, replay, and runner gates pass.

A callable in `CELL_RUNNERS` is not by itself proof of execution readiness.
The original SkillFlow N4 cell is expected to report
`method_release_incompatible` until the new release exists. The frozen
OfficeQA cell may report `insufficient_attribution_coverage` without changing
its operator semantics.

## 10. Replay and audit

Every N4 invocation writes an application-isolated replay pack:

```text
runtime_noise/
└── <task_id>/
    └── <application_id>/
        └── N4/
            ├── input.json
            ├── output.json
            ├── audit.json
            ├── protected_state.json
            ├── token_usage.json
            └── timing.json
```

`audit.json` records:

- method, method release, benchmark, dataset release, task, attempt,
  application, and replicate identity;
- adapter, policy, operator, and spec versions;
- original attribution, eligible candidate IDs, and selected candidate;
- seed and stable selection identity;
- before/after fragments and hashes;
- protected-state comparison;
- applicability and reason code.

Files contain no credentials. Large evidence is represented by portable
locator and content hash. An existing replay path with different content is an
error, not an overwrite.

## 11. Failure policy

Expected non-applicability is recorded with stable reason codes:

- `missing_native_feedback`;
- `unparseable_original_attribution`;
- `ambiguous_original_attribution`;
- `no_grounded_decoy`.

Invariant failures stop the application:

- `adapter_roundtrip_mismatch`;
- `protected_state_mismatch`;
- `invalid_candidate_evidence`;
- `replay_identity_collision`;
- `method_release_incompatible`.

The first group returns the unchanged learner-visible feedback plus an audit.
The second group is a failed cell/application and cannot be counted as a null
effect.

## 12. Verification strategy

Implementation follows test-first development.

### Contract and generic-operator tests

- backward-compatible parsing of old `FeedbackRecord` JSON;
- explicit trajectory arguments on every adapter;
- scalar reward and protected-state preservation;
- deterministic candidate selection;
- budget exactly one;
- alias exclusion;
- fail-closed behavior with no fallback;
- replay collision and repeated-application isolation.

### Domain fixture tests

- Spreadsheet parseable range, same-shape decoy, execution error, alias, and no candidate cases;
- OfficeQA standalone axis, quoted-value protection, ambiguous axis, gold non-leakage, and no-attribution cases;
- WebShop coherent `LocalizedFault` replacement and no same-class candidate;
- SkillFlow valid/invalid analyzer JSON, missing event/skill refs, same-class decoy, and immutable `TrialOutcome`.

### Method and frozen-identity tests

- SkillOpt, SkillAdaptor, and SkillLearn adapter round trips;
- temporary SkillFlow patch replay after the original patch series;
- no modifications to original SkillFlow source, release, patch hashes, or fingerprint;
- candidate method identity differs from original SkillFlow;
- clean hook identity for frozen methods;
- analyzer parity between clean/noisy arms of the modified method.

### Provider-free preflight

- no provider client construction or completion calls;
- per-cell implementation and method-release compatibility states;
- protected-state and replay schema fixtures;
- frozen clean-evidence applicability report;
- related test suites and static checks.

Formal N4 execution requires, per cell:

```text
feedback_bearing_count > 0
applicable_count > 0
protected_state_failures == 0
audit_missing_count == 0
```

All inapplicable applications remain in the fixed denominator and are grouped
by reason. Paid execution must not begin while preflight reports an incompatible
method release or insufficient attribution coverage.

## 13. Expected first-pass readiness

| Domain | First-pass result |
|---|---|
| Spreadsheet | implementation and provider-free validation ready |
| OfficeQA | strict implementation ready; formal cell may remain coverage-blocked |
| WebShop | implementation and provider-free validation ready; reference vertical slice |
| SkillFlow | operator, adapter, candidate patch, and fixtures ready; formal run blocked on new clean release |

This separation prevents code completeness from being confused with scientific
or execution readiness.
