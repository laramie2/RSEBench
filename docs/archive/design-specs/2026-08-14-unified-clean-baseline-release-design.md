# Unified Clean Baseline and Robust Validation Design

Date: 2026-08-14

## Objective

Build one publishable and reproducible experiment control plane for the four
clean self-evolution benchmark cells, then use one frozen clean release to
unlock parallel N1–N4 validation. Experiments run from the canonical `main`
checkout; Git worktrees remain a development tool and are not experiment
identities or result-freezing mechanisms.

The clean benchmark cells are:

| Domain | Benchmark | Baseline |
|---|---|---|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt |
| Document QA | OfficeQA Full | SkillOpt |
| Interactive | WebShop | SkillAdaptor |
| Skill learning | SkillLearnBench | separated-round self-feedback |

The design separates two questions that the current qualification result
conflates:

1. Can the baseline execute a complete self-evolution workflow and adopt an
   artifact without degrading clean performance?
2. Does the adopted artifact produce a stable, strictly positive clean gain?

Only a benchmark cell that satisfies both questions may enter N1–N4.

## Current evidence and migration status

The stopped clean-v1 matrix is diagnostic evidence, not the final clean
release.

- Spreadsheet/SkillOpt completed all three seeds. Two seeds adopted updates
  and improved clean score by `+0.0667` and `+0.1333`; the third did not
  update. This establishes both operational and efficacy evidence for the
  current cell.
- OfficeQA/SkillOpt completed three processes but adopted no update. Runtime
  recovery, validation headroom, and integration failures invalidate the cell.
- WebShop/SkillAdaptor produced two positive clean gains (`+0.20` and `+0.05`)
  but the formal runs were invalidated by task-ID normalization, action-parser,
  and Linker JSON failure paths. The third seed terminated before a result.
- SkillLearn `organize-messy-files` completed three seeds and adopted two
  updates per seed, but every score remained `0.0 -> 0.0`. One
  `offer-letter-generator` seed adopted two updates and remained
  `0.3333 -> 0.3333`. These runs prove execution, not efficacy.

SkillLearn v1 is retained as a diagnostic pilot. Its observed clean-test
outcomes are not reused to claim a formal v2 qualification.

All four cells rerun under the unified clean-v2 result contract. Spreadsheet
is rerun even though its pilot is successful because the v2 contract adds
baseline fingerprints, immutable experiment identities, parallel isolation,
and three-level timing that the old result lacks.

## Baseline source and patch model

External baseline source is not vendored and does not use Git submodules.
Every baseline is defined by:

- an upstream repository URL;
- one immutable upstream commit;
- an ordered patch series;
- a SHA-256 for every patch;
- a runtime dependency lock and interpreter identity.

The robust repository tracks the registry, patch series, adapters, tests, and
bootstrap code. Materialized checkouts live in gitignored
`methods/external/`.

The baseline bootstrap is idempotent:

1. clone the declared upstream repository if absent;
2. verify the remote URL;
3. checkout the exact registered commit;
4. apply the patch series in declared order;
5. verify patch hashes and that reverse checks succeed;
6. compute a baseline fingerprint;
7. verify that no unregistered source changes exist.

Bootstrap and patch application take an exclusive source lock. Formal
experiments take a shared read lock and may never modify the baseline source
checkout. A run checks the baseline fingerprint before and after execution.

Compatibility and robustness patches remain explicitly distinguishable from
upstream behavior. Reports name baselines using the form:

```text
SkillOpt@<upstream-commit> + <ordered-patchset-hash>
SkillAdaptor@<upstream-commit> + <ordered-patchset-hash>
```

## Canonical repository organization

`main` is the sole experiment and GitHub release branch. The existing feature
implementation and baseline-repair work are integrated into `main` after the
current pilot is archived. The temporary development worktrees are removed
only after their commits and diagnostic artifacts are accounted for.

The target layout is:

```text
benchmark/
  registry/                 # Baseline, dataset, and benchmark version locks
  validation/               # Frozen clean-v2 manifests
  core1/                    # N1-N4 noise specifications and manifests

patches/baselines/
  skillopt/
    series.yaml
    *.patch
  skilladaptor/
    series.yaml
    *.patch

configs/experiments/
  clean-v2.yaml
  n1.yaml
  n2.yaml
  n3.yaml
  n4.yaml

src/rsebench/experiments/
  contracts.py              # Identity, result, failure, timing contracts
  bootstrap.py              # Clone, patch, verify, fingerprint
  runner.py                 # One experiment unit
  scheduler.py              # Parallel scheduling, isolation, recovery
  release.py                # Immutable release manifest and summaries

methods/external/            # Gitignored pinned baseline checkouts
data/                        # Gitignored materialized datasets
outputs/                     # Gitignored full logs, trajectories, ledgers
releases/                    # Tracked compact contracts and result summaries
```

Experiment scripts may not rely on an editable package installed from another
worktree. Entry points resolve the package from the canonical checkout or use
an installed environment whose source commit matches the experiment identity.

## Experiment identity

Each unit has a deterministic `experiment_id` derived from canonical JSON
containing:

- robust repository commit;
- baseline repository URL and revision;
- ordered patch names and hashes;
- environment/dependency fingerprint;
- experiment manifest hash;
- dataset, task, and seed-skill hashes;
- model, provider, and runtime configuration;
- benchmark, stage, and method seed.

Each execution attempt has a separate `attempt_id`. Retrying an interrupted
unit preserves its `experiment_id` and creates a new `attempt_id`. Any code,
patch, data, task, model, or runtime change creates a new `experiment_id`.
Results with different experiment identities cannot be combined to satisfy a
three-seed qualification.

## Unified execution contract

Every clean unit follows the same state flow:

```text
prepare
-> seed clean evaluation
-> clean acquisition/evolution
-> clean validation and native adoption
-> freeze evolved artifact
-> evolved clean evaluation
-> qualification
```

The clean test is read only. Its content and outcomes never enter reflection,
artifact editing, candidate selection, validation, runtime calibration, or
sample replacement.

Baseline adapters have a narrow responsibility:

- materialize the unified manifest into native baseline inputs;
- invoke the native baseline through a declared environment;
- collect artifact versions, native validation decisions, and task results;
- translate provider, parser, protocol, timeout, and infrastructure exceptions
  into typed failures;
- report execution evidence without making benchmark-level qualification
  decisions.

Qualification is implemented once in the common experiment layer.

## Result and timing contract

Every completed or failed attempt writes a typed `result.json` with these
sections:

```text
identity
scores
evolution
execution
timing
usage
qualification
```

Required contents include:

- experiment, attempt, run, benchmark, baseline, stage, and seed identity;
- repository, baseline, patch, manifest, task, and artifact hashes;
- seed and evolved aggregate scores plus task-level scores;
- accepted/rejected updates and native validation trajectory;
- execution coverage and typed failure categories;
- billed/logical token totals and observation coverage;
- engineering and efficacy decisions with explicit failure reasons.

Timing uses UTC ISO 8601 timestamps for auditability and a monotonic clock for
durations. It is recorded at three levels:

1. **Run:** queued, started, ended, and total wall duration.
2. **Stage:** prepare, seed evaluation, evolution, validation/adoption,
   artifact freeze, and evolved clean evaluation.
3. **Task:** each task or episode start, end, duration, status, attempt, and
   failure category.

Per-model-call latency remains in the append-only token ledger. `result.json`
summarizes call count and latency distribution by stage instead of duplicating
every call record.

Interrupted attempts write an interruption record and retain append-only token
and timing events. They do not write a successful qualification and never
count toward a fixed denominator.

## Two-level clean readiness

A method-seed is engineering-valid when all of the following hold:

- selected acquisition, validation, and clean-test coverage is 100%;
- no systemic infrastructure, provider, parser, timeout, or protocol failure
  invalidates the run;
- the evolved artifact semantic hash differs from the seed artifact;
- at least one update passes the baseline's native clean validation gate;
- evolved clean score is greater than or equal to seed clean score.

A benchmark/baseline cell is `engineering_ready` when at least two of its three
fixed method seeds are engineering-valid.

A cell is `efficacy_ready` when it is engineering-ready and at least two of
three fixed seeds have strictly positive clean gain. Only efficacy-ready cells
may enter N1–N4.

The two decisions remain separately visible. An artifact update with
`0.0 -> 0.0` may demonstrate engineering execution but is never described as
effective self-evolution.

## Clean-v2 benchmark cells

### SpreadsheetBench-Verified / SkillOpt

Reuse the confirmation-scale clean split and runtime that produced two
positive pilot seeds, but execute all three fixed seeds through the unified
runner. The result is not imported as final evidence because the old results
lack the v2 identity and timing contract.

### OfficeQA Full / SkillOpt

Use the v2 `12/12/20` split, the released `hard` primary gate with 1% relative
numeric tolerance, three update steps, batch size four, two workers, 12 tool
turns, and 4096 completion tokens. The bounded recovery patch permits one
normal recovery after unstructured output and then requires a best-effort
answer rather than repeated analysis. The underdetermined UID0240 exclusion is
recorded as a benchmark amendment rather than hidden as a runtime repair.

### WebShop / SkillAdaptor

Keep the frozen `5/5/20` task order, three iterations, 15 episode steps,
lexical retrieval threshold 0.10, and native five-example validation gate.
The patchset normalizes numeric task IDs at the integration boundary, uses a
real executable action fallback after deterministic parse repair, and isolates
one malformed Linker candidate rather than terminating the seed. Calibration
retrieval evidence is stored as a portable, hashed benchmark artifact instead
of referencing an untracked worktree output.

### SkillLearnBench / self-feedback

Clean v1 remains diagnostic. Before v2 is frozen, perform a provider-free and
offline audit of:

- instance startup and official verifier completion;
- seed-skill injection into every episode;
- acquisition feedback visibility and validation isolation;
- semantic differences in accepted skills;
- seed floors, validation headroom, and verifier failure categories.

The v2 split is designed from calibration evidence that is disjoint from its
final clean test. Observed v1 final-test results cannot be used to cherry-pick
individual v2 final-test instances. Each selected v2 family runs all three
fixed method seeds from the beginning.

## Parallel scheduler and resource isolation

The scheduling unit is:

```text
benchmark x baseline x stage x method_seed
```

The scheduler does not serialize solely by baseline name. It serializes by a
declared `mutable_resource_key`. A baseline checkout that is verified read-only
may be shared concurrently by different benchmark units.

Each adapter declares a parallel-safety profile:

```yaml
source_checkout: shared_readonly
parallel_safety: isolated_runtime
max_parallel: 2
mutable_resources: []
```

Every unit receives an isolated output root, temporary directory, cache root,
token ledger, environment snapshot, and runtime-generated split. Checkpoints,
logs, temporary skills, and dynamic configuration may not be written to the
shared source checkout. If an adapter cannot isolate a mutable resource, only
units sharing that resource key are serialized.

This permits Spreadsheet and OfficeQA to run concurrently against one
read-only SkillOpt checkout. SkillLearn containers use unique names and have
explicit stop/cleanup handling. Provider, CPU, memory, Docker, and baseline
limits are independently configurable. `--max-parallel` is an overall cap,
not the only resource constraint.

## Scheduler state and recovery

Unit states are:

```text
pending -> queued -> running -> completed
                         |-> failed
                         |-> interrupted
                         |-> invalid
```

One unit failure does not stop unrelated units. The scheduler maintains:

- `matrix_status.json` as an atomic current snapshot;
- `events.jsonl` as append-only state history;
- one immutable directory per attempt;
- typed stdout/stderr, timing, usage, and failure records.

Resume skips only a completed unit with the exact expected `experiment_id`.
Interrupted, failed, or invalid attempts remain visible and restart in a new
attempt directory. Old directories are never overwritten. Manual edits to a
result cannot upgrade an experiment identity.

## Stage barriers and N1–N4

The global flow is:

```text
baseline bootstrap verified
-> clean engineering readiness
-> clean efficacy readiness
-> immutable clean release
-> N1-N4 unlocked
```

N1–N4 use the same runner, result contract, timing, scheduler, and baseline
fingerprints as clean. A noise experiment references exactly one
`clean_release_id`. It may not alter the clean task order, method seeds, seed
artifact, model/runtime configuration, or baseline patchset unless it declares
a new clean release first.

N1–N4 may run in parallel after the clean barrier. Noise experiments never
trigger patch application or source mutation. Their only permitted differences
are those declared by the frozen noise-stage manifest.

## CLI

The public workflow is:

```bash
rsebench baselines bootstrap
rsebench baselines verify

rsebench experiment preflight \
  --matrix configs/experiments/clean-v2.yaml

rsebench experiment run \
  --matrix configs/experiments/clean-v2.yaml \
  --max-parallel 4

rsebench experiment status --run-id <run-id>
rsebench experiment aggregate --run-id <run-id>
rsebench release freeze --run-id <run-id>
```

A noise run is:

```bash
rsebench experiment run \
  --matrix configs/experiments/n1.yaml \
  --clean-release <clean-release-id> \
  --max-parallel 4
```

Real provider calls require an explicit `experiment run`. Bootstrap, verify,
preflight, status, aggregate, and release validation do not call a model.

## GitHub release artifacts

Git tracks code, registries, patches, dependency locks, frozen manifests,
compact aggregates, timing/token summaries, and human-readable reports. It
does not track secrets, external baseline clones, raw datasets, complete
trajectories, per-call ledgers, Docker state, or large run directories.

Each frozen release has:

```text
releases/<track>/<release-id>/
  manifest.json
  qualification.json
  aggregate.json
  timing-summary.json
  token-summary.json
  report.md
```

The manifest records the complete reproducibility contract, original local
run IDs, and hashes of summarized raw artifacts. Release creation fails if a
secret scan finds provider credentials or if any referenced identity/hash is
missing. Raw artifacts remain locally addressable by run ID and may be
archived separately without becoming part of the Git repository.

## Testing and verification

Testing has four layers:

1. Unit tests for canonical hashing, schemas, timing, qualification, state
   transitions, and secret redaction.
2. Adapter contract tests using fake baselines to verify materialization,
   failure translation, output isolation, and result collection.
3. Baseline bootstrap replay that clones registered commits and verifies every
   ordered patch can be applied and reversed.
4. Provider-free preflight that validates task counts/order, data resolution,
   commands, timing hooks, parallel resource keys, and output isolation.

Concurrency tests run two units against a fake shared read-only checkout and
assert that all writes remain within unit directories. Interruption tests stop
the scheduler and SkillLearn containers, then verify append-only evidence and
clean restart behavior.

Real DeepSeek experiments are never automatically triggered in GitHub CI.
They require an explicit local command and credentials from an untracked
environment. Tests and release generation scan outputs for secret patterns.

## Migration sequence

1. Archive the stopped clean-v1 matrix as a diagnostic pilot report, including
   result identities, failure categories, timing available from logs, and the
   observed 100% token accounting.
2. Integrate the complete pilot implementation and baseline repair commits
   into `main`; do not modify historical result files.
3. Implement the unified bootstrap, contracts, three-level timing, runner,
   scheduler, and release layer.
4. Rebuild external baseline checkouts from registered commits and replay the
   ordered patch series.
5. Freeze all four clean-v2 manifests and run provider-free preflight plus
   parallel-isolation tests.
6. Run one failure-targeted canary per cell: Spreadsheet adapter regression,
   OfficeQA hard-gate/update recovery, WebShop former seed-three crash, and one
   calibrated non-floor SkillLearn family.
7. If a canary causes any code/config change, generate new experiment
   identities and restart all three formal seeds for the affected cell.
8. Run the four three-seed clean-v2 cells with safe parallelism.
9. Compute engineering and efficacy readiness, freeze the clean release only
   when all four cells are efficacy-ready, and publish the compact release
   artifacts.
10. Remove temporary development worktrees after their commits and artifacts
    are accounted for, then launch N1–N4 only by reference to the frozen clean
    release.

## Acceptance criteria

The design is implemented when:

- one canonical `main` checkout can bootstrap and verify all registered
  baselines from scratch;
- clean, N1, N2, N3, and N4 use one runner and result schema;
- each result contains valid run-, stage-, and task-level timing;
- same-baseline/different-benchmark units can run concurrently when their
  adapters declare isolated runtime resources;
- interruption never leaves a running SkillLearn container or silently counts
  a partial unit;
- all four clean cells satisfy both readiness levels under three fixed seeds;
- a secret-safe, deterministic clean release can be committed to GitHub;
- N1–N4 refuse to start without an efficacy-ready immutable clean release.
