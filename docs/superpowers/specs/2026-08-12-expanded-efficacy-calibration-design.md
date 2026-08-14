# Expanded Noise-Efficacy and Document-QA Calibration Design

Date: 2026-08-12

## Objective

Expand the spreadsheet and mathematics paired self-evolution pilots to reduce
small-sample uncertainty, repair the OfficeQA environment mismatch that caused
floor behavior, and continue searching for noise operators that degrade noisy
self-evolution relative to clean self-evolution without contaminating the clean
test set.

This remains a feasibility phase. It does not authorize full-dataset benchmark
runs or implementation of the proposed robust self-evolution method.

## Approaches considered

### A. Direct full-scale expansion

Run all frozen evolution and test records immediately. This maximizes sample
size, but spends substantial API budget before confirming that the environment
is calibrated and that the current operators have an effect. It is rejected for
this phase.

### B. Reuse existing skills and expand only clean-test evaluation

Evaluate the already evolved spreadsheet and DAPO skills on larger untouched
test sets. This is the cheapest way to estimate whether current differences
persist, but it does not test whether larger evolution sets change the learned
skills. It is useful as an initial checkpoint but insufficient by itself.

### C. Staged medium-scale expansion with calibration gates

First expand clean-test evaluation of existing skills, then regenerate and rerun
medium-sized evolution splits only where the signal remains plausible. Repair
OfficeQA using its official evidence and scoring contract, calibrate on a
separate pool, freeze a non-floor/non-ceiling subset, and only then generate
paired noise. This is the selected approach because it provides stronger
evidence while bounding cost and preventing test-driven sample selection.

## Global experimental invariants

Every reported comparison must satisfy all of the following:

1. Both arms start from the same byte-identical seed skill.
2. Both arms use the same task IDs, task order, method seed, model, generation
   parameters, and optimization budget.
3. Noise is applied only to evolution train and validation records.
4. Clean test records remain byte/hash identical across seed, clean-evolved, and
   noisy-evolved evaluations.
5. Noise candidates are selected only by predeclared construction hard gates;
   clean-test performance is never used for candidate inclusion.
6. Calibration tasks are disjoint from evolution train, validation, and final
   clean test.
7. Identical skill hashes reuse a single evaluation result.
8. Provider, tool, parser, or timeout failures are reported separately and are
   never converted into ordinary task scores.
9. All model calls use exactly `deepseek-v4-flash` through
   `https://api.deepseek.com` with thinking disabled.

## Phase 1: cheap expanded evaluation of existing skills

### SpreadsheetBench-Verified

Evaluate the existing seed, clean-evolved, and noisy-evolved skill artifacts on
the first 30 tasks of the already frozen `pilot_eval`/test order, excluding the
eight tasks already used only when computing an incremental-cost summary. The
primary report uses all 30 tasks.

The existing evolution run remains 5 train / 5 validation. This checkpoint asks
whether the observed `+0.125` evolution gap persists under a larger untouched
test sample before paying to repeat evolution.

### DAPO fixed 1000

Evaluate the existing seed, clean-evolved, and noisy-evolved skills on the first
50 tasks of the frozen test partition. The primary report uses all 50 tasks and
includes the original ten.

This checkpoint distinguishes a true zero effect from the observed two-task
cancellation. Per-task transitions are reported as clean-correct/noisy-wrong,
clean-wrong/noisy-correct, both-correct, and both-wrong counts.

### Checkpoint decision

Proceed to new medium-scale evolution when at least one of these holds:

- absolute evolution gap is at least 0.05;
- at least three net harmful task flips favor the clean-evolved skill;
- the clean/noisy skills remain behaviorally different and the paired interval
  is still too wide to decide.

If none holds, redesign the operator before another evolution run.

## Phase 2: medium-scale paired evolution

### Spreadsheet configuration

- Evolution train: 20
- Validation: 10
- Clean test: 30
- Maximum evolution steps: 3
- Batch size: 5
- Workers: 2
- Maximum task turns: retain the verified spreadsheet setting

Start with the currently effective C1 failed-attempt prompt operator. If its
expanded evolution gap is below 0.05, compare one C2 workbook operator selected
before execution: semantic decoy sheet. Do not select between operators using
clean-test scores from multiple candidates; each attempted operator is reported.

### Mathematics configuration

- Evolution train: 15
- Validation: 8
- Clean test: 50
- Maximum evolution steps: 3
- Batch size: 5
- Workers: 2
- Maximum task turns: 1

Start with the current C1 model-generated flawed partial solution. Generation
keeps the existing gates: one localized error, critic-confirmed invalidity,
answer-leak rejection, structural validity, label invariance, and solvability.
Hard-gate backfill may scan up to four times the requested sample count in frozen
order. Exhaustion is a rejected generation run, not permission to weaken gates.

If path divergence persists but the 50-task aggregate gap stays below 0.05, the
next operator is a C2 evidence-style derivation trace with one stale intermediate
value. That operator requires a separate design amendment before implementation.

## Phase 3: OfficeQA root-cause repair and calibration

### Diagnosed mismatch

The earlier OfficeQA run did not reproduce the benchmark's intended environment:

- official oracle parsed pages were not loaded;
- the native 24-round tool budget was reduced to 6;
- completion length was reduced from 16384 to 2048;
- questions needing external official data had no search path;
- the harness used strict exact match rather than OfficeQA's official numerical
  tolerance scorer.

The floor must be repaired at these boundaries before changing noise.

### Evidence materialization

Download the official parsed JSON files referenced by the gated OfficeQA release
and retain the already materialized transformed text corpus. The adapter must
resolve each `source_docs` page number to the matching parsed JSON page and record:

- resolved source file count;
- oracle page count and character count;
- local tool rounds;
- whether external evidence was required;
- final answer extraction status;
- official score and failure category.

The materializer writes an index of file hashes and counts. It never writes the
HF token into data, logs, commands, or manifests.

### Scoring contract

Use OfficeQA's released `score_answer` semantics with a fixed 1% relative numeric
tolerance. Also retain exact match as a secondary diagnostic. Candidate-skill
selection and final reporting use the same official-tolerance score.

### Search policy

The primary calibrated lane is oracle-page plus local-document tools. Questions
whose required operand is absent from the released oracle/local evidence are
classified as `external_evidence_required` during calibration and are not used
in the offline primary lane.

No unauthenticated or unstable public web-scraping service is added. A future
web-grounded lane requires a separately versioned search provider and cache; it
must not be mixed with the offline lane.

### Runtime calibration

Use an independent 30-task calibration pool drawn from the frozen OfficeQA
evolution partition, stratified by released `difficulty` label and source-file
count. Evaluate the seed skill under three cumulative settings:

1. corrected oracle pages + 6 tool rounds + 4096 completion tokens;
2. corrected oracle pages + 12 tool rounds + 4096 completion tokens;
3. corrected oracle pages + 24 tool rounds + 8192 completion tokens.

Stop at the cheapest setting satisfying all calibration gates:

- seed score is between 0.25 and 0.75 inclusive;
- at least 80% of tasks return a parseable final answer;
- systemic provider/tool failure rate is below 5%;
- at least 12 eligible offline tasks remain after excluding
  `external_evidence_required` cases.

If no setting satisfies the gates, OfficeQA remains blocked and no noisy
self-evolution result is reported.

### Frozen paired OfficeQA pilot

After selecting the runtime setting, freeze a new disjoint split:

- Evolution train: 12
- Validation: 6
- Clean test: 20

Sampling is stratified by released difficulty and source-file count using only
calibration-derived eligibility rules, not task correctness. The selected IDs,
eligibility reason, and source group are written to an immutable manifest before
noise generation.

Run the following operators in declared order:

1. C1 failed attempt in the question;
2. C3 gold-rank displacement in candidate retrieval;
3. C2 semantic decoy evidence only if the first two produce less than a 0.05
   evolution gap.

Every attempted operator is reported, including null results.

## Metrics and success criteria

For every domain/operator report:

- seed score;
- clean-evolved score and gain;
- noisy-evolved score and gain;
- evolution gap = clean-evolved minus noisy-evolved;
- paired bootstrap 95% interval;
- reverse-evolution flag;
- per-task transition counts;
- selected-skill hashes and validation trajectories;
- task, token, tool-round, and wall-clock budgets;
- construction rejection and systemic failure counts.

An operator passes the expanded feasibility gate when:

1. clean-evolved score is not below the seed score by more than 0.02;
2. evolution gap is at least 0.05;
3. the noisy arm has either a smaller gain or reverse evolution;
4. at least three net harmful paired flips favor the clean arm;
5. the result has no systemic failure and all test tasks are untouched clean
   records.

The confidence interval is reported but is not required to exclude zero at this
medium-scale feasibility stage. Final benchmark claims will require multiple
seeds and larger test sets.

## Error handling and stopping rules

- A provider-wide failure aborts the run immediately.
- A missing artifact, source page, or task ID fails materialization before model
  calls.
- Hard-gate rejection triggers only frozen-order backfill within the declared
  candidate budget.
- A calibration setting that misses the score window is recorded and the next
  cumulative setting is tried.
- No more than three OfficeQA runtime settings and three noise operators are
  attempted in this phase.
- If three operator designs in one domain fail the efficacy gate, stop and revisit
  the domain/benchmark choice rather than tuning on the clean test.

## Verification

Implementation must add tests for:

- expanded clean-test manifests and non-overlap;
- evaluation-only reuse of existing evolved skills;
- OfficeQA parsed-page resolution and fail-fast behavior;
- official 1% scorer parity with the released reward function;
- calibration eligibility independent of task correctness;
- calibration stop selection;
- same-seed/same-budget paired manifests;
- per-task transition accounting;
- secret redaction.

Before experimental conclusions are updated, the main harness, full SkillOpt
suite, focused baseline adapter tests, patch reversibility checks, and tracked-file
secret scan must pass.
