# Expanded N1 Validation Design

## Objective

Test whether task-context noise (N1) reduces self-evolution quality when the
evolution and validation sets are large enough for the baseline's update gate
to operate. The comparison remains paired: one frozen seed, matched clean/noisy
task IDs, and one untouched clean test split.

## Domain cells

| Domain | Benchmark / baseline | Expanded validation unit |
|---|---|---|
| Spreadsheet | SpreadsheetBench-Verified / SkillOpt | 8 train, 4 validation, 20 clean test |
| Document QA | OfficeQA / SkillOpt | 8 train, 4 validation, 20 clean test |
| Interactive | WebShop / SkillAdaptor | 5 train, 3 validation, 10 clean test |
| Skill learning | SkillLearnBench / self-feedback | four independent families; per family 2 acquisition, 1 validation, 2 clean test |

SkillLearn families are independent statistical units. Skills are never shared
between unrelated families. Instance scores and family-level success rates are
both reported.

## Noise programs

- Spreadsheet: append a plausible prior handover that changes exactly one task
  constraint while preserving workbook and verifier.
- OfficeQA: append a prior analyst derivation that changes exactly one of period,
  unit, or aggregation while preserving source documents and gold answer.
- WebShop: append a prior-session recommendation of a real near-match product
  that violates exactly one hard constraint.
- SkillLearnBench: append an instance-specific brittle workflow that appears
  useful for the acquisition instance but should not transfer reliably.

All train and validation examples receive N1 in the noisy arm. The clean test is
never mutated.

## Sequential gates

1. Seed score must be strictly between 0.10 and 0.90.
2. Clean evolution must produce a semantic artifact different from the seed or
   record at least one accepted update.
3. Clean evolved score must be no lower than seed score.
4. Only cells passing gates 1--3 run the noisy arm.
5. A candidate N1 effect requires clean evolved score greater than noisy evolved
   score on the untouched clean test.
6. A positive candidate is not promoted until the direction repeats in three
   independent paired runs.

Preflight failures are experimental results. They are reported as floor,
ceiling, no-update, or clean-reverse rather than as evidence that N1 is null.

## Cost controls

- DeepSeek V4 Flash only, thinking disabled.
- Token accounting includes completed, blocked, and interrupted calls.
- Seed evaluation precedes evolution; clean evolution precedes the noisy arm.
- SkillLearn family calibration evaluates two held-out instances before any
  acquisition round.
- No N2/N3/N4 experiment runs in this validation round.

## Outputs

- Portable expanded N1 manifests under `benchmark/validation/n1_expanded/`.
- Per-cell preflight and paired run artifacts under
  `outputs/runs/n1-expanded-20260813/`.
- A result report separating dataset validity, seed calibration, clean update,
  noise effect, and replication status.
