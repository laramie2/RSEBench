# Current Robust Self-Evolution Validation Status

Date: 2026-08-13

## Executive conclusion

The shared harness now supports hash-audited paired self-evolution: clean and
noisy arms start from the same seed skill, use the same task IDs, task order,
method seed, optimizer budget, and untouched clean test split. All online calls
in this phase used exactly `deepseek-v4-flash` at `https://api.deepseek.com`
with thinking disabled. No GPT model was used.

The expanded validation result is deliberately mixed:

- **Spreadsheet passed the medium-scale efficacy gate.** With 20 train, 10
  validation, and 30 untouched clean-test tasks, clean evolution improved from
  `0.2333` to `0.4000`, while evolution on C1 failed-attempt noise remained at
  `0.2333`. The clean-minus-noisy gap is `+0.1667`, with paired bootstrap 95%
  interval `[0.0333, 0.3000]`. Clean evolution accepted a skill update; noisy
  evolution rejected every update. This is evidence that noise disrupted the
  self-evolution process, rather than merely degrading final inference.
- **DAPO math did not pass.** A strict C1 flawed-partial-solution pipeline
  generated 15 train and 8 validation pairs after rejecting 9 candidates, but
  both arms rejected all three skill updates and retained the same seed skill.
  Seed, clean-evolved, and noisy-evolved scores are all `0.6800` on 50 clean
  test tasks. The operator is valid data, but not an effective evolution-noise
  operator for this SkillOpt configuration.
- **OfficeQA calibration is repaired.** Oracle parsed pages cover every task,
  official scoring is reproduced, and `12` tool rounds with `4096` completion
  tokens passed the preregistered calibration gates. The frozen formal split is
  12 train / 6 validation / 20 clean test, with a `0.5000` seed score and no
  floor or ceiling. C1 prompt noise produced zero gap. C3 rank displacement
  changed the selected skill but improved, rather than harmed, clean-test score
  from `0.5000` to `0.5500`. C2 semantic-decoy evidence also produced zero gap
  and retained the seed in both arms.

Therefore only the spreadsheet operator is currently eligible as a positive
robustness-benchmark component. Math and the completed document operators must
be reported as null or opposite-direction results, not selected away.

## Protocol and decision rules

For every paired run:

1. Noise is applied only to evolution train and validation records. Formal test
   records remain clean and are hash-audited.
2. Noise candidates must pass structural validity, label invariance,
   solvability, and answer-leak gates before materialization.
3. Hard-gate backfill follows frozen manifest order and never reads a clean-test
   score. Rejected candidates remain in the generation audit.
4. Seed, clean-evolved, and noisy-evolved skills are evaluated on the same clean
   test tasks. Identical skill hashes reuse one evaluation, preventing duplicate
   stochastic calls from creating a false gap.
5. A medium-scale operator passes the current feasibility gate only when the
   clean-minus-noisy evolution gap is at least `0.05` and its direction is
   supported by paired task transitions. Confidence intervals, including those
   crossing zero, are always reported.

The exercised cross-domain taxonomy is:

- `C1/M2`: misleading or flawed task-side reasoning context;
- `C2/M1`: additive evidence or artifact distractors;
- `C3/M5`: retrieval order and evidence-access displacement.

## Expanded paired results

| Domain / operator | Train / val / test | Seed | Clean evolved | Noisy evolved | Gap | 95% paired CI | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| SpreadsheetBench-Verified, C1 failed attempt | 20 / 10 / 30 | 0.2333 | 0.4000 | 0.2333 | +0.1667 | [0.0333, 0.3000] | Pass |
| DAPO, C1 flawed partial solution | 15 / 8 / 50 | 0.6800 | 0.6800 | 0.6800 | 0.0000 | [0.0000, 0.0000] | Null; both arms retained seed |
| OfficeQA, C1 failed attempt | 12 / 6 / 20 | 0.5000 | 0.5000 | 0.5000 | 0.0000 | [0.0000, 0.0000] | Null; both arms retained seed |
| OfficeQA, C3 gold-rank displacement | 12 / 6 / 20 | 0.5000 | 0.5000 | 0.5500 | -0.0500 | [-0.2500, 0.1500] | Opposite direction |
| OfficeQA, C2 semantic-decoy documents | 12 / 6 / 20 | 0.4000 | 0.4000 | 0.4000 | 0.0000 | [0.0000, 0.0000] | Null; both arms retained seed |

### Spreadsheet details

The earlier 5/5/8 pilot suggested a `+0.125` gap, but evaluating those old skills
on 30 test tasks reversed the conclusion: seed and clean were `0.3333`, noisy
was `0.4667`, and clean-minus-noisy was `-0.1333` with interval
`[-0.2667, -0.0333]`. This result was retained and triggered the declared
medium-scale rerun rather than being discarded.

The medium run then produced the positive result. Validation improved from
`0.60` to `0.70` in the clean arm, which accepted one update. The noisy arm's
validation baseline was `0.80`; all four attempted steps failed to improve it,
so the arm retained its seed skill. On formal test there were 7 both-correct,
18 both-wrong, and 5 clean-correct/noisy-wrong transitions.

Run:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T141243410275Z-skillopt`

Generation:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/evolution-noise/20260812T141159229114Z-54d9cb6bcf`

### Mathematics details

The old 5/3/10 artifacts were first evaluated on 50 test tasks. Seed/noisy scored
`0.6800`, clean scored `0.6200`, and clean-minus-noisy was `-0.0600` with
interval `[-0.1800, 0.0600]`. Four tasks favored clean and seven favored noisy;
the clean skill itself was the unstable component.

The medium generator then attempted 23 candidates to retain 15 train and 8
validation records; 9 candidates were rejected under the 18-attempt per-task
limit. Rejection causes include invalid or truncated JSON, gold-answer leakage,
failure to confirm exactly one localized error, and an independent critic
judging the attempt valid. No gate was relaxed. In the paired run, clean
validation was `0.3750`, noisy validation was `0.5000`, and neither arm accepted
an update. Both final skill hashes equal the seed hash.

Run:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T151342302045Z-skillopt`

Generation:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/evolution-noise/20260812T143117286818Z-3adb2c600f`

### OfficeQA calibration and operator details

All 246 OfficeQA rows have materialized parsed-page evidence. The 30-task
calibration pool is disjoint from the frozen 12/6/20 experiment split and was
selected using released difficulty and source-file-count strata, not task
correctness.

| Runtime | Score | Parseable | Systemic failure | Oracle pages | Eligible | Gate |
|---|---:|---:|---:|---:|---:|---|
| 6 rounds / 4096 tokens | 0.5667 | 0.7000 | 0.0000 | 1.0000 | 29 | Fail parseability |
| 12 rounds / 4096 tokens | 0.6667 | 0.8333 | 0.0000 | 1.0000 | 29 | Pass and selected |

Calibration:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/officeqa-calibration/20260812T135014695288Z-skillopt`

Frozen split:
`/home/nvidia/yutao/lzt/self-evolution-robustness/data/splits/officeqa_calibrated/split_manifest.json`

C1 retained the same skill in both arms after three rejected updates. The 20-task
test was `0.5000` with `0.9000` parseability, so the null result is not a floor
artifact.

C3 lowered noisy validation from the clean seed's `0.8333` to `0.5000`. The
noisy arm then accepted step 2 after improving to `0.6667`; the clean arm kept
the seed. On formal clean test, however, the new skill scored `0.5500`. Paired
transitions were 8 both-correct, 7 both-wrong, 2 clean-only, and 3 noisy-only.
This is mechanism evidence but the wrong direction for the intended benchmark.

C2 added eight query-related, answer-leak-screened decoy documents while
keeping all gold documents at rank 1. Both clean and noisy validation baselines
were `0.8333`, and both arms rejected all three updates. The run's seed score
was `0.4000` with `0.7500` parseability; clean and noisy final scores remained
identical. The difference from the C1/C3 run-level seed score (`0.5000`) is
DeepSeek rollout variance across independent runs, not a paired comparison
artifact: each paired run shares its own seed/test realization, and identical
skill hashes reuse the same evaluation within that run.

C1 run:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T152847183826Z-skillopt`

C3 run:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T155946233702Z-skillopt`

C2 run:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T164334977961Z-skillopt`

## Dataset and baseline readiness

| Dataset | Local and harness state | Current efficacy state |
|---|---|---|
| SpreadsheetBench-Verified | Materialized, frozen, native train/eval passed | Positive medium-scale C1 result |
| OfficeQA | 246 rows plus 285 referenced parsed JSON hardlinks; official scorer and calibrated runtime passed | C1 null, C2 null, C3 opposite direction |
| DAPO fixed 1000 | Materialized with frozen 400/100/500 partition; native numeric evaluator passed | Strict C1 null at medium scale |
| LiveMathematicianBench | Downloaded, profiled, and split | Retained as alternate math source; not used in current medium run |
| DocVQA 10% | 534 rows and images materialized | Visual online execution blocked because the selected DeepSeek endpoint rejects `image_url` |
| SearchQA SkillOpt split | Official IDs and payload materialized; native C1/C2 paths passed | Repeated `1.0000` ceiling; negative/control lane |
| Skill-native datasets | Distribution and format audit retained | Mechanism/diagnostic lane only |

Seven baseline repositories pass real DeepSeek transport, structured-output,
and tool-use smoke tests. This proves API adaptation, not full shared evolution
support. SkillOpt remains the only method wired end to end to the paired harness
across all three current domains.

| Baseline | DeepSeek API/tool smoke | Shared paired self-evolution |
|---|---|---|
| Trace2Skill | Passed | Not yet connected |
| SkillOpt | Passed | End-to-end in spreadsheet, OfficeQA, and DAPO |
| SkillGrad | Passed | Not yet connected |
| EvoSkill | Passed | Not yet connected |
| Skills-Coach | Passed | Not yet connected |
| SkillFlow | Passed | Not yet connected |
| FederatedSkill | Passed | Not yet connected |

## Current next gate

Do not start the full multi-method benchmark yet.

1. Retain spreadsheet C1 as the positive operator and reproduce it with at least
   one additional baseline before making a general cross-method claim.
2. Redesign math noise at the evolution-feedback level or use a less explicitly
   dismissible provenance-conflict operator; the current labeled flawed attempt
   is valid but does not drive a selected skill update.
3. Redesign document noise around conflicting provenance/evidence attribution
   while retaining oracle solvability. The current C1/C2 operators are too weak,
   while C3 changes the update path in the opposite direction.
4. Only operators that reproduce a harmful evolution gap without hurting clean
   benchmark validity should enter the final robust benchmark release.

The execution-ready screening, confirmation, token-budget, and stopping rules
are frozen in `docs/plans/next-validation-experiments.md`.

## Token accounting

All future noise generation, calibration, paired evolution, and expanded
evaluation runs now write an append-only per-call token ledger. The default
budget view is provider-billed usage; cache hits are reported separately through
the logical-token view.

The historical exact lower bound is `24,670,510` billed tokens across `3,282`
observable calls. Another `588` legacy evaluation conversations have no
persisted provider usage and remain unobservable rather than estimated. The
live ledger smoke measured 11 billed tokens for one request and 22 logical
tokens after one identical cache hit. Full definitions, source breakdown, and
artifact paths are in `docs/reports/token-accounting-status.md`.

## Reproducibility verification

- Main benchmark and harness suite: `210 passed`.
- Focused external SkillOpt token/backend/environment suite: `13 passed`.
- The tracked SkillOpt adaptation patch reverse-applies cleanly to the current
  external checkout, so the intentionally dirty external repository is fully
  represented by the versioned patch.
- Tracked-file secret scan passed; API and Hugging Face credentials remain only
  in ignored environment files and are not copied into reports or artifacts.
