# Core-1 Hybrid Evolution-Evidence Noise Design

Date: 2026-08-13

## 1. Objective

Build the first executable Core-1 release candidate of RSEBench across four
peer domains:

| Domain | Core-1 benchmark | Primary validation method |
|---|---|---|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt |
| Document QA | OfficeQA | SkillOpt |
| Skill Learning | SkillLearnBench | Self-Feedback; Teacher-Feedback for explicit N4 confirmation |
| Real-world / Interactive | WebShop | SkillAdaptor |

The validation question is not whether noise lowers one noisy inference score.
For a fixed seed skill, model, task split, budget, and method seed, compare
self-evolution on clean versus noisy evolution evidence and evaluate both final
skills on the same untouched clean test tasks.

Mathematics is not an active Core-1 domain. Existing mathematical datasets,
code, and historical results remain archived and auditable, but active
registries and validation reports must not count them toward the four-domain
benchmark.

## 2. Benchmark definition

RSEBench is an executable hybrid benchmark:

1. N1 and N2 are versioned static paired task/environment artifacts.
2. N3 and N4 are deterministic runtime mutation programs operating on method
   outputs at two declared hook boundaries.
3. Every runtime mutation emits a replayable before/after evidence pack.
4. A fixed reference replay pack is released for cheap updater-only analysis,
   but headline results execute the full closed self-evolution loop.

The four stages are mutually exclusive for a single validation cell:

```text
task instance -> environment interaction -> stored trajectory -> update feedback
      N1                  N2                     N3                 N4
```

- N1 mutates task-side context before the first action.
- N2 mutates an execution-visible artifact or observation source while
  preserving the original solution and verifier.
- N3 mutates the stored trajectory after execution and before reflection.
- N4 mutates reflection, critique, or fault attribution after it is produced
  and before the skill update.

`add`, `stale`, `omit`, and `replace` are operator implementation metadata, not
independent experiment dimensions.

## 3. Public evidence interface

### 3.1 Normalized records

`rsebench.evidence` exposes strict JSON-compatible records:

```python
class TraceEvent:
    event_id: str
    step_index: int
    kind: Literal["instruction", "action", "observation", "artifact_diff", "message"]
    action: str | None
    observation: str | None
    resource_refs: list[str]
    tags: list[str]
    metadata: dict[str, Any]

class TrajectoryRecord:
    task_id: str
    benchmark: str
    events: list[TraceEvent]
    reward: float | None
    success: bool | None
    metadata: dict[str, Any]

class FeedbackRecord:
    task_id: str
    benchmark: str
    summary: str
    blamed_event_ids: list[str]
    blamed_resources: list[str]
    recommendations: list[str]
    scalar_reward: float | None
    metadata: dict[str, Any]
```

The scalar reward is protected. N3 cannot alter it. N4 cannot alter it or the
trajectory.

### 3.2 Runtime specification

Every N3/N4 cell ships a `RuntimeNoiseSpec` containing:

- benchmark, domain, stage, operator, version, seed, and budget;
- an exact deterministic selector name and selector parameters;
- an applicability policy;
- a failure policy fixed to `record_not_applicable`, never silent fallback to a
  different operator;
- protected field names.

The mutation engine returns a `MutationResult` containing normalized input and
output hashes, selected event/resource IDs, an applicability flag, reason,
operator version, seed, and reversible before/after fragments. The result is
written before the method receives the mutated object.

### 3.3 Hook contract

Python methods use:

```python
class EvidenceAdapter(Protocol):
    def normalize_trajectory(self, native: Any, context: HookContext) -> TrajectoryRecord: ...
    def denormalize_trajectory(self, record: TrajectoryRecord, native: Any) -> Any: ...
    def normalize_feedback(self, native: Any, context: HookContext) -> FeedbackRecord: ...
    def denormalize_feedback(self, record: FeedbackRecord, native: Any) -> Any: ...
```

The benchmark-owned hook calls:

```python
hook.after_rollout(native_trajectory, context)   # identity or N3
hook.after_feedback(native_feedback, context)    # identity or N4
```

Non-Python methods use the same contract through JSON files and
`rsebench evidence-mutate`. The process reads one normalized record plus one
runtime spec and writes one mutated record plus one audit file. This makes the
benchmark usable without importing baseline internals.

Adapters are responsible only for lossless normalization and denormalization.
Operator selection and mutation remain benchmark-owned so future work cannot
quietly reinterpret N3/N4.

### 3.4 Clean parity and fail-closed behavior

- With no runtime spec, the hook returns the original native object byte-for-
  byte where serialization permits, otherwise structurally equal.
- A configured N3/N4 operator that cannot find an eligible target records
  `applicable=false`; it must not choose a different corruption.
- Validation reports applicability separately and cannot count a no-op as a
  noisy example.
- Each baseline adapter must pass an identity-hook parity smoke before an
  efficacy run.

## 4. Core-1 operators

One L2 operator is screened per stage and domain.

| Domain | N1 | N2 | N3 | N4 |
|---|---|---|---|---|
| SpreadsheetBench-Verified | related erroneous handover | unlabeled stale semantic sheet | omit one critical workbook-edit event | replace blamed sheet/range |
| OfficeQA | one-axis misleading analyst derivation | same-indicator different-period Treasury source | omit oracle-source open/read event | replace blamed source/period/unit |
| SkillLearnBench | non-generalizable acquisition handover on instance-1 | competing stale resource in instance-1 container | omit one artifact-producing action-observation pair | replace self/teacher diagnosis before revision |
| WebShop | near-match prior-session note | real catalog near-match promoted in search results | omit one required option/query-refinement event | replace first actionable fault step |

### 4.1 SpreadsheetBench-Verified

Protected objects are the original instruction, all original sheets, the answer
sheet/range, and the gold workbook/verifier.

- N1 appends a non-authoritative handover that omits exactly one real constraint
  such as the second join key or dynamic-range requirement. The existing
  failed-attempt operator is retained as the validated implementation.
- N2 copies a task-relevant source sheet under a realistic prior-period name,
  preserves headers, and changes dates/numbers without warning labels. All
  original sheet digests must remain identical.
- N3 normalizes `conversation.json` tool/action records and removes one event
  tagged `workbook_write` whose artifact diff intersects a nonempty edited
  range. Save and final response events are ineligible.
- N4 preserves the rollout and verifier score but replaces the true failing
  sheet/range in analyst-visible verification text with a same-shaped decoy
  range from the same workbook.

### 4.2 OfficeQA

Protected objects are the question, answer, all released source files, oracle
pages, official scorer, and retrieval budget.

- N1 appends an analyst note that changes one observed question axis: calendar
  versus fiscal year, nominal versus real, unit, aggregation, or requested
  entity. It may not contain a normalized gold answer.
- N2 selects a real Treasury Bulletin document with matching entity/table terms
  but a different period or unit and places it with the oracle in top-3. The
  oracle appears exactly once and remains accessible.
- N3 removes one complete action-observation event that opens or reads an oracle
  source. Search and final-answer events are preserved.
- N4 replaces only the analyst-visible failure attribution among source,
  period, unit, and aggregation. Retrieved text, answer, official score, and
  trajectory remain unchanged.

### 4.3 SkillLearnBench

The unit of evolution is a task family. Only `instance-1` is used for skill
acquisition; every remaining instance in that family is a clean evaluation
task. Hidden tests and reference solutions are never exposed to the learner.

- N1 appends a plausible instance-1 handover that recommends a brittle fixed
  workflow, such as fixed PDF coordinates or hard-coded workbook columns.
- N2 uses a resource dispatcher: old form/field map, prior-year workbook,
  deprecated API/config, old media asset, or backup file. The original resource
  remains unchanged and the oracle still passes.
- N3 removes one filesystem-changing terminal action and its observation from
  the first-round trace shown to the revision round.
- N4 first materializes self-reflection or teacher guidance, then changes one
  diagnosis target before skill rewriting. Teacher-Feedback is the primary N4
  screen because it exposes a native feedback boundary; Self-Feedback uses the
  same split boundary without receiving hidden verifier details.

### 4.4 WebShop

Protected objects are the original goal, target catalog records, valid actions,
reward function, and target reachability.

- N1 attaches a prior-session note naming a real near-match product that
  violates exactly one hard goal constraint.
- N2 promotes real catalog near-matches to top-5 while retaining at least one
  valid target in top-10.
- N3 removes one action-observation pair tagged as a required option selection
  or the query refinement that first makes a valid target reachable.
- N4 changes SkillAdaptor's localized `step_index` to another eligible action
  step and updates the corresponding observation/action fields before Linker
  and Reviser run. Reward and trajectory remain unchanged.

## 5. Baseline integration points

### SkillOpt

The RSEBench patch adds an optional hook in trajectory formatting. N3 mutates a
loaded conversation immediately before analyst formatting. N4 mutates the
failure-reason/verification attribution immediately before the analyst prompt.
The rollout result and official score files remain canonical. Spreadsheet and
OfficeQA use the current DeepSeek-compatible executor and token ledger.

### SkillLearnBench Self-/Teacher-Feedback

The adapter registers a DeepSeek API terminal agent and separates acquisition
round execution, normalized trace/reflection, and skill rewrite. Identity mode
must reproduce the official round count, skill layout, and verifier behavior.
The final skill is evaluated on clean non-instance-1 tasks.

### SkillAdaptor

N3 runs on each native `Trajectory` before Localizer. N4 runs on
`LocalizedFault` after Localizer and before Linker. The external patch is kept
as a versioned patch file; credentials remain environment-only.

## 6. Validation protocol

### 6.1 Applicability smoke

Run 2 examples per cell without self-evolution. Required:

- accepted structural/label/solvability/leakage gates for N1/N2;
- applicable deterministic mutation and successful replay for N3/N4;
- identity-hook parity for each baseline;
- complete mutation audit and token ledger.

### 6.2 Efficacy screen

Use the smallest nontrivial paired evolution split supported by each benchmark:

| Benchmark | Evolution / validation / clean test |
|---|---:|
| SpreadsheetBench-Verified | 5 / 3 / 10 |
| OfficeQA | 6 / 3 / 10 |
| SkillLearnBench | 1 acquisition instance per selected family / native remaining instances |
| WebShop | 5 / 3 / 10 goals |

Use `deepseek-v4-flash`, thinking disabled, identical budgets and seeds across
arms. A cell is a candidate only if:

1. clean evolution does not underperform the seed;
2. clean and noisy skill hashes or update traces differ;
3. clean-minus-noisy score on untouched clean test is at least 0.05;
4. no systemic failure or budget mismatch occurs;
5. all noisy evolution examples are applicable.

Null and opposite results remain in the report. No operator is retuned after a
clean-test score is observed. At most two candidates per domain can later move
to confirmation, with priority N3, N4, N2, N1.

## 7. Release artifacts

The pilot produces:

```text
benchmark/core1/
  static/{benchmark}/{N1,N2}/
  runtime/{benchmark}/{N3,N4}.json
  manifests/
  schemas/
outputs/runs/core1-screen/<run-id>/
  clean/
  noisy/
  mutation_audit/
  replay_pack/
  token_usage/
  result.json
  report.md
```

The report distinguishes four states for every cell: `passed`, `null`,
`opposite`, or `blocked`. A blocked cell is never reported as evidence of
robustness failure.
