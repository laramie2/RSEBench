# Clean Baseline Qualification Design

Date: 2026-08-13

## Objective

Before running any additional N1 arm, establish that the selected baseline can
complete useful clean self-evolution reproducibly in each of the four Core-1
benchmark domains. Qualification uses three independent method seeds on frozen
clean data. A benchmark passes only when at least two of the three runs produce
an accepted semantic artifact update and the evolved artifact does not
underperform its seed on the untouched clean test.

The four benchmark/baseline cells are:

| Domain | Benchmark | Baseline |
|---|---|---|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt |
| Document QA | OfficeQA Full | SkillOpt |
| Interactive | WebShop | SkillAdaptor |
| Skill learning | SkillLearnBench | self-feedback |

SkillAdaptor is the WebShop baseline. SkillLearnBench continues to use the
separated-round self-feedback executor and is evaluated at family level.

## Approaches considered

### A. Reuse the expanded-N1 pilot sizes

Reuse 8/4/20 for Spreadsheet and OfficeQA, 5/3/10 for WebShop, and the first
four runnable SkillLearn families. This is the cheapest option and preserves
direct comparability with the previous N1 run. It is rejected because the
validation sets have coarse score resolution, the prior SkillOpt budget allows
only one update, and selecting only runnable SkillLearn families would conceal
the cross-family failure rate.

### B. Confirmation-scale clean-only qualification

Use the already designed confirmation-scale Spreadsheet and OfficeQA splits,
increase WebShop validation and test coverage, execute all eight preregistered
SkillLearn candidate families, and run three fixed method seeds. Repair only
demonstrated runtime or adapter faults before the formal runs. This is the
selected approach because it directly tests the observed instability without
spending on a noisy arm whose baseline precondition is unmet.

### C. Full-dataset clean evolution

Run the maximum available official partitions for every baseline and family.
This would provide the strongest aggregate estimate but would spend heavily
before the execution and update paths are qualified. It is deferred until the
confirmation-scale gate passes.

## Global experimental contract

The formal method seeds are `20260813`, `20260814`, and `20260815`. All three
runs in a benchmark cell share byte-identical task IDs, task order, seed skill,
model configuration, runtime budget, evaluator, and scoring implementation.
Only the baseline method seed differs.

Every formal run follows this order:

1. evaluate the seed artifact on the frozen clean test;
2. evolve only on clean acquisition tasks;
3. select updates only on clean validation tasks;
4. freeze the evolved artifact and its semantic hash;
5. evaluate that artifact on the same frozen clean test;
6. persist task-level outcomes, update decisions, failures, and token usage.

The clean qualification runner must not load noisy prompts, generate N1
records, or dispatch a noisy arm. Clean-test content and outcomes never enter
reflection, artifact editing, validation selection, runtime calibration, or
sample replacement. Test performance is read only after the artifact is
frozen.

Seed floor or ceiling is a diagnostic, not a reason to skip clean evolution.
Infrastructure, provider, parser, protocol, and timeout failures remain typed
failures and are never converted to ordinary zero scores.

If a baseline or runtime changes after a formal run begins, the configuration
version changes and all three method seeds restart. Results produced by
different configuration versions cannot be combined to satisfy qualification.

All model calls use `deepseek-v4-flash`, temperature 0, and thinking disabled.

## Frozen sample and runtime settings

| Benchmark | Acquisition | Validation | Clean test | Evolution/runtime budget |
|---|---:|---:|---:|---|
| SpreadsheetBench-Verified | 20 | 10 | 30 | SkillOpt: 3 update steps, batches 7/7/6, 2 workers, 3 tool turns, 2048 completion tokens |
| OfficeQA Full | 12 | 6 | 20 | SkillOpt: 3 update steps, batches 4/4/4, 2 workers, 12 tool turns, 4096 completion tokens |
| WebShop | 5 | 5 | 20 | SkillAdaptor: at most 3 iterations, 15 episode steps, validation minimum sample size 5 |
| SkillLearnBench | 2/family | 1/family | all remaining 2-3/family | self-feedback: one round per acquisition instance, 16 tool turns, 4096 completion tokens |

The task manifests record source partition, selected IDs, ordered hashes,
runtime settings, method seeds, seed artifact hashes, scorer version, and
baseline revision. Sample IDs stay fixed across the three method seeds.

### SpreadsheetBench-Verified

Use the existing confirmation-scale 20/10/30 design over the frozen official
partitions. The first two SkillOpt steps consume seven acquisition tasks each
and the third consumes the remaining six, so every acquisition task
participates once. Preserve SkillOpt's native validation gate and persist every
candidate artifact, validation score, accepted/rejected decision, and semantic
hash.

The clean test retains the official cell-range verifier. Its 30 examples give
score resolution of approximately 0.033, while the ten-example validation set
reduces the gate resolution from the previous 0.25 to 0.10.

### OfficeQA Full

Use the already calibrated, disjoint 12 acquisition / 6 validation / 20 test
split. Restore the selected offline runtime of 12 tool turns and 4096
completion tokens; the previous expanded N1 run's 3-turn/2048-token settings
are not eligible for qualification.

Use the released OfficeQA scoring semantics with a fixed 1% relative numeric
tolerance. Each formal run must also report:

- parseable final-answer rate, which must be at least 0.80;
- systemic provider/tool failure rate, which must be below 0.05;
- resolved source-file and oracle-page counts;
- missing-page, external-evidence, parser, and provider failure categories.

Failure of these runtime gates makes the method seed an execution failure, not
an ordinary low-scoring run.

### WebShop

Retain SkillAdaptor as the primary WebShop baseline. RethinkSkill is not used
in qualification. Before the formal seeds, perform an unscored adapter
preflight that does not inspect evolved or clean-test outcomes:

1. make lexical retrieval use a lexical-appropriate threshold or retrieval
   rule rather than the semantic threshold inherited by the fallback path;
2. persist, for every episode, candidate skill IDs, similarity values,
   retrieved IDs, and the skills actually injected into the policy prompt;
3. verify that the general WebShop seed skill reaches the policy prompt;
4. retain complete exception type and message instead of silently mapping
   `RuntimeError` to a zero reward;
5. repair the failure observed on goal `994`;
6. replay and verify the existing DeepSeek embedding-compatibility patch;
7. use a 15-step episode horizon instead of the truncated eight-step pilot.

Retrieval calibration may use only acquisition/validation retrieval coverage,
never task correctness on the clean test. Any formal episode lacking its audit
record is an execution failure.

The five validation tasks are frozen after the repaired seed calibration. The
predeclared rule selects, in the existing structural candidate order, the first
two seed successes and the first three seed failures. This targets a non-floor,
non-ceiling seed validation score near 2/5 and does not use evolved, noisy, or
clean-test outcomes.

Use five structurally selected acquisition tasks and twenty untouched clean
test tasks. SkillAdaptor runs at most three iterations and retains its native
validation/adoption logic with `min_sample_size=5`.

### SkillLearnBench

Execute all eight preregistered candidate families:

1. `organize-messy-files`;
2. `offer-letter-generator`;
3. `schedule-planning`;
4. `dependency-vulnerability-check`;
5. `github-repo-analytics`;
6. `financial-analysis`;
7. `stock-data-visualization`;
8. `enterprise-information-search`.

For each family, freeze the first two structurally ordered instances as clean
acquisition, the third as validation, and all remaining two or three available
instances as clean test. Skills never cross family boundaries. Each family
runs all three method seeds, yielding 24 formal SkillLearn runs.

The runner must not apply a seed-score gate before evolution. A zero-scoring
seed still executes both acquisition rounds, each validation evaluation, and
the final clean-test evaluation. Every selected instance must start its
container, complete the agent interaction, and return an official verifier
result.

Docker images and fixed dependencies are materialized before formal metering,
and their hashes are recorded. Formal runs may not trigger opportunistic
external downloads. The completion limit is 4096 tokens to avoid the malformed
tool-call truncation observed in the earlier stock-data run.

## Qualification rules

A method-seed run succeeds only when all of the following hold:

1. acquisition, validation, and clean-test execution coverage is 100%;
2. no infrastructure, provider, parser, timeout, or protocol failure invalidates
   a selected task;
3. the final artifact has a semantic hash different from the seed artifact;
4. at least one artifact update was accepted by the baseline's native
   validation gate;
5. evolved clean-test score is greater than or equal to seed clean-test score.

Strictly positive clean gain is reported as a secondary efficacy measure but
is not silently added to the qualification gate.

SpreadsheetBench, OfficeQA, and WebShop each qualify when at least two of their
three method-seed runs succeed.

SkillLearn qualifies at two levels:

- a family qualifies when at least two of its three method-seed runs succeed;
- the benchmark qualifies only when at least four of the eight preregistered
  families qualify.

Every failed seed and family stays in the result table. Families cannot be
backfilled or replaced after outcomes are observed.

## Execution order and N1 barrier

1. implement and test a clean-only runner that cannot dispatch a noisy arm;
2. complete the WebShop retrieval/error preflight and SkillLearn container
   preflight;
3. materialize and hash all clean qualification manifests;
4. execute the three formal Spreadsheet seeds;
5. execute the three formal OfficeQA seeds;
6. execute the three formal WebShop seeds;
7. execute all 24 formal SkillLearn family/seed cells;
8. aggregate qualification status and token accounting;
9. freeze the resulting baseline configuration versions.

No N1 arm in any domain starts until all four benchmark-level qualification
gates pass. A qualified N1 experiment must reuse the same task IDs, task order,
method seeds, seed artifacts, model, runtime, evolution budget, and clean test.
Only the acquisition and validation records may change from clean to their
already specified N1 counterparts.

## Audit outputs

The implementation will create:

- portable clean-only manifests under
  `benchmark/validation/clean_qualification_v1/`;
- append-only formal runs under
  `outputs/runs/clean-qualification-20260813/`;
- one per-run record containing configuration/version hashes, execution
  coverage, seed/evolved scores, clean gain, artifact hashes, validation
  trajectory, task-level outcomes, typed failures, and token usage;
- one aggregate record with 2/3 benchmark decisions and SkillLearn family
  qualification rates;
- a human-readable report that explicitly separates execution validity,
  artifact update stability, clean efficacy, and N1 eligibility.

The formal workload contains 33 clean evolution units: three Spreadsheet,
three OfficeQA, three WebShop, and 24 SkillLearn family/seed runs.
