# Next Robustness Validation Experiments

Date: 2026-08-13

## Objective and promotion rule

The next round is not a general noise survey. Its purpose is to identify
benchmark components for which evolution on a paired noisy train/validation set
causes a reproducible loss on an untouched clean test set, while evolution on
the paired clean data remains useful. Null and opposite-direction results stay
in the audit and cannot be discarded after observing test scores.

Do not start full multi-method expansion until all of the following hold:

1. at least two task domains show a clean-minus-noisy evolution gap of at least
   `0.05` at confirmation scale;
2. at least two baseline families show the harmful direction, including one
   cross-method replication on the same benchmark component;
3. clean evolution accepts a non-identical skill and does not underperform the
   seed on the confirmation test;
4. the direction is reproduced with a second preregistered method seed, or the
   paired 95% interval excludes zero on the first confirmation and the second
   seed is scheduled before benchmark freeze.

## Unified experimental contract

Every candidate uses one frozen source split and creates task-aligned clean and
noisy evolution arms. The arms share task IDs, order, seed skill, method seed,
optimizer budget, target model, maximum turns, and evaluation code. Noise is
allowed only in train and validation. The formal test set stays clean and its
hash is checked before and after both arms.

The reusable noise meta-families are:

| Family | Perturbed object | Cross-domain interpretation |
|---|---|---|
| C1: task-observation conflict | Prompt, worked trace, or task-local context | Misleading but relevant observations supplied with the task |
| C2: environment/evidence conflict | Workbook, document set, or retrieved evidence | Competing artifacts that preserve the gold evidence and answer |
| C3: access/order conflict | Retrieval rank, tool result order, visibility schedule | Correct evidence remains accessible but is displaced or delayed |
| C4: learning-signal provenance conflict | Evolution trace, critique, attribution, or update evidence | Plausible learning evidence is bound to the wrong source or conclusion |

Operators may be rule-based, model-based, or hybrid, but must emit the same
pair manifest and pass structural validity, label invariance, solvability, and
answer-leak gates. Model-based candidates use only `deepseek-v4-flash` with
thinking disabled. Test performance is never consulted by generation,
backfill, or candidate selection.

For each run report seed, clean-evolved, and noisy-evolved scores; clean and
noisy gains; paired evolution gap and 95% bootstrap interval; per-task harmful
and helpful flips; skill hashes; accepted/rejected update steps; validation
trajectory; failure categories; and billed/logical token usage by arm and
stage.

## Execution order

### 1. Spreadsheet: reproduce the positive C1 result across methods

Use SpreadsheetBench-Verified and retain the existing model-generated
`failed_attempt` C1/M2 operator. SkillOpt's 20/10/30 result is the reference,
not a new selection target.

First connect Trace2Skill to the shared `evolve`/`evaluate` contract. The
adapter must consume the same pair manifest, use DeepSeek API transport rather
than its CLI model path, persist the evolved skill, and evaluate both arms with
the same official cell-range verifier. Before an efficacy run, require a 2/1/2
adapter smoke with non-empty model output, correct task IDs, and complete token
events.

Run a 10/5/10 Trace2Skill screen. Promote only if clean and noisy skill hashes
diverge or their update traces differ and the observed gap is positive. Then
run the frozen 20/10/30 confirmation with the same noise records used for the
SkillOpt experiment. If the gap is at least `0.05`, repeat the confirmation
with a second method seed. Do not regenerate examples between methods.

Primary question: does the same noisy evolution data harm both an
optimizer-style skill editor and a trace-to-skill method?

### 2. Mathematics: replace the dismissible failed-attempt operator

The labeled flawed partial solution is retained as a null result. Screen two
new operators on DAPO using 5 train / 3 validation / 10 clean test:

- **C1 unlabeled provenance conflict:** attach two concise, plausible
  intermediate derivations without marking either as a failed attempt. Exactly
  one contains one localized contradiction; neither contains a final answer.
  A rule checker verifies symbol/number consistency and two independent model
  critics verify one-error localization, solvability, and no gold leakage.
- **C4 feedback-attribution corruption:** materialize the normal rollout and
  critique records, then bind a critique to a difficulty-matched different
  task or to the wrong intermediate claim. Task questions, gold answers, and
  clean-test evaluation remain unchanged. The permutation is deterministic,
  bijective, and stored in the noise manifest.

Before comparing noise, require the clean arm to accept at least one update.
If DAPO again retains the seed under the clean arm, stop that candidate without
using its test gap and repeat the 5/3/10 screen on the already downloaded
LiveMathematicianBench split. This is a benchmark suitability decision, not an
operator selection by test score.

Promote only after the clean skill differs from the seed and the noisy update
path differs from clean. Confirmation uses 15/8/50 and the exact accepted
screening template. A harmful gap below `0.05`, identical final skills, or a
clean-evolution loss returns the operator to the null ledger.

### 3. OfficeQA: target evidence attribution, not mere retrieval clutter

Keep the calibrated 12-round/4096-token offline runtime and the disjoint formal
split. Screen on 6 train / 3 validation / 10 clean test:

- **C2 conflicting-source attribution:** retain every oracle page at rank 1 and
  add a structurally matched decoy excerpt whose period, unit, or table header
  conflicts with the oracle. Metadata makes both sources plausible but never
  removes the oracle or inserts the gold answer.
- **C4 citation-to-claim binding swap:** preserve retrieved text verbatim while
  permuting citations or provenance labels among difficulty- and source-count-
  matched evolution examples. Store the bijection and inverse in the manifest.

Generation gates additionally require all oracle pages present, no systemic
provider or missing-page failures, parseable-answer rate at least `0.80`, and a
seed score in `[0.25, 0.75]`. Promote only if the clean/noisy update paths
diverge and the clean-minus-noisy gap is positive. Confirmation uses the frozen
12/6/20 split. After a SkillOpt confirmation, connect EvoSkill to the same
OfficeQA task and scoring contract and repeat the accepted operator; the
10-question EvoSkill demo is never substituted for formal OfficeQA.

## Stage gates and stopping rules

| Gate | Screening decision | Confirmation decision |
|---|---|---|
| Generation validity | 100% label invariant; at least 80% candidate acceptance within preregistered backfill budget | Same frozen operator and validator versions |
| Clean evolution | At least one accepted non-identical update before reading the noise gap | Clean score must be no worse than seed; positive gain is preferred |
| Mechanism effect | Clean/noisy hashes or update trajectories differ | Net harmful flips greater than zero |
| Efficacy | Positive gap permits confirmation | Gap at least `0.05`; report paired 95% interval regardless of crossing zero |
| Reproducibility | One fixed method seed | Second seed after pass; no operator retuning between seeds |
| Failure | Floor/ceiling, provider/systemic failure, or identical paths stops expansion | Null/opposite result is retained and reported |

A noisy arm that improves over clean is an opposite-direction result. It is not
renamed as a control or removed. An operator may be redesigned only with a new
version and a new preregistered screening run.

## Token budget and dispatch policy

Budget gates use `billed_tokens.total_tokens`; cache-inclusive logical usage is
reported but does not consume the provider budget. Check the ledger after each
generation candidate batch, evolution step, and evaluation stage.

| Experiment | Screening cap | Confirmation cap |
|---|---:|---:|
| Spreadsheet operator, per method seed | 300,000 | 1,200,000 |
| Math generation plus paired evolution, per operator | 800,000 | 2,500,000 |
| OfficeQA generation plus paired evolution, per operator | 1,500,000 | 4,000,000 |

Stop before dispatching the next batch or step when the cap is reached. A
single in-flight response may take the final total above the cap and must still
be recorded. Do not increase a cap because an observed gap is promising;
changes require a new run version. Provider failures remain unobservable and
count against the attempted-call stopping rule even though their tokens cannot
be charged to the measured billed total.

## Planned deliverables before benchmark freeze

1. Trace2Skill paired SpreadsheetBench adapter and cross-method C1 result.
2. Versioned math C1/C4 generators with manifests, hard-gate audit, and one
   suitability-qualified confirmation or retained null result.
3. Versioned OfficeQA C2/C4 generators and one SkillOpt confirmation; EvoSkill
   replication only after a positive operator is frozen.
4. One shared result table containing all positive, null, and opposite runs,
   paired intervals, trajectory diagnostics, and token usage.
5. Only after the promotion rule is met: freeze the robustness benchmark and
   begin the proposed robust self-evolution pipeline comparison on both noisy
   and original clean benchmarks.
