# Core-1 noise design and validation status

Date: 2026-08-13

## Executive conclusion

The Core-1 benchmark slice is now executable across four peer domains. It has
16 frozen stage manifests, materialized N1/N2 pairs, fixed N3/N4 runtime specs,
baseline adapters, mutation replay packs, and paired clean/noisy evaluation on
one untouched clean test split.

This is an **interface and screening milestone, not an efficacy claim**. None
of the current noise cells should yet be promoted into the final benchmark:

- Spreadsheet N3 produced a promising `0.20` clean-minus-noisy gap once, but
  the all-applicable confirmation produced a `0.00` gap and both arms reverse
  evolved. The candidate signal did not replicate.
- OfficeQA N1 and N4 are no longer at a systemic parser floor, but SkillOpt
  rejected every proposed update; the noise therefore had no update to
  influence.
- WebShop N1 reached a non-floor seed score, but SkillAdaptor adopted no new
  skill. The earlier N3 run proves the hook is applied, but its test score was
  at a zero floor.
- The first SkillLearnBench family reverse evolved in both arms. The replacement
  family scored zero at the seed calibration gate, so it is unsuitable for an
  efficacy comparison with the current model and harness.

The correct next experimental unit is consequently not “run all 16 cells at
larger scale.” It is: calibrate a non-floor task family, require a real clean
update, then screen one noise stage and replicate the paired result before
promotion.

## Released Core-1 design

| Domain | Core-1 benchmark | Baseline | N1: task context | N2: environment evidence | N3: stored trajectory | N4: update feedback |
|---|---|---|---|---|---|---|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt | append a plausible but wrong handover changing one task constraint | add an unlabeled stale semantic sheet while preserving originals | omit one tagged workbook-write event | redirect blamed sheet/range to a same-shape decoy |
| Document QA | OfficeQA | SkillOpt | append a prior derivation changing one period/unit/aggregation axis | rank a real same-topic conflicting-period source with the oracle | omit one oracle-source open/read event | redirect source/period/unit attribution |
| Skill Learning | SkillLearnBench | self-feedback; teacher-feedback for N4 | append an instance-specific brittle workflow | add a competing stale resource without changing hidden tests | omit one true artifact-production event | redirect the diagnosis to a same-kind decoy step |
| Interactive | WebShop | SkillAdaptor | name a real near-match product violating one hard constraint | promote that near match while retaining a valid target | omit a required-option/query-refinement event | redirect the localized actionable fault step |

All operators use mutation budget one. A stage that cannot find its declared
target records `applicable=false`; it does not silently fall back to a different
noise mechanism. Mathematics is not part of the active Core-1 matrix.

N1 and N2 are fixed, distributable clean/noisy task pairs. N3 and N4 are hybrid:
the release fixes the split, operator, selector, seed, budget, protected fields,
and failure policy, while the evaluated method supplies the native trajectory or
feedback at runtime. The resulting `input.json`, `output.json`, and `audit.json`
form the generated, method-specific replay datum.

Materialization output:

- `benchmark/core1/materialization.json`: 16/16 profiles generated;
- hard gates: structural validity, solvability, label invariance, and answer-leak
  checks all pass;
- `benchmark/core1/splits/<benchmark>/<N1..N4>.json`: paired evolution and clean
  test manifests;
- `benchmark/core1/static_data/`: fixed N1/N2 overlays;
- `benchmark/core1/runtime/`: fixed N3/N4 mutation programs.

All 16 manifests use portable `rsebench-data://`, `rsebench-methods://`, or
`rsebench-project://` locators. A post-materialization audit found zero current
machine absolute paths and successfully resolved 265 referenced local
artifacts/fixtures through the declared roots.

## N3/N4 integration contract

Future baselines install the same hook in two native learning boundaries:

```python
hook = EvidenceNoiseHook.from_spec_files(
    adapter=MethodAdapter(),
    spec_paths=[n3_spec, n4_spec],
)

# Native reward/verifier has run; reflection has not.
trajectory_for_learning = hook.after_rollout(native_trajectory, context)

# Native reflection/localization has run; revision/update has not.
feedback_for_update = hook.after_feedback(
    native_feedback,
    native_trajectory,
    context,
)
```

The method adapter supplies four conversions: normalize and denormalize a
trajectory, and normalize and denormalize feedback. N3 must preserve task ID,
environment state, scalar reward, and success. N4 must preserve the trajectory
and scalar reward. The clean arm returns the exact native object by identity.

This design lets a future method generate N3/N4 data normally without shipping
one misleading “universal model-output dataset.” The released spec determines
the mutation; the method's rollout determines its input; the replay pack makes
the exact generated sample portable and auditable.

## Validation protocol and promotion gates

Every efficacy cell starts from the same seed artifact, evolves on paired
clean/noisy versions of the same training IDs, and evaluates both artifacts on
the same unmodified clean test IDs.

The gates are sequential:

1. **Validity:** labels, verifier, task identity, protected fields, and clean
   test data are unchanged.
2. **Seed calibration:** the seed score must be strictly between floor and
   ceiling, with no systemic harness failure. Core-1 now supports a configurable
   exclusive seed-score interval and stops before evolution if it fails.
3. **Applicability:** runtime operators report applicable/inapplicable tasks;
   the efficacy subset must meet the declared coverage threshold.
4. **Clean evolution:** the baseline must actually produce an update, and clean
   evolution must not be worse than the seed. A no-op update gate cannot validate
   a noise mechanism.
5. **Noise effect:** `score(clean-evolved) - score(noisy-evolved) > 0` on the
   untouched clean test, with different learning evidence/artifacts.
6. **Replication:** because API inference is not bit-deterministic even at
   temperature zero, the direction must replicate across independent paired
   runs before promotion. The final benchmark should additionally report a
   task-paired bootstrap interval and multiple method/model seeds.

The seed gate applies to cheap validation and operator search. It is not a rule
that removes hard examples from the final benchmark; final benchmark reporting
must expose the complete frozen split and its score distribution.

## Experiments completed

| Domain / stage | Train / val / clean test | Seed | Clean evolved | Noisy evolved | Gap | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| Spreadsheet N3, initial expanded | 5 / 3 / 10 | 0.50 | 0.60 | 0.40 | +0.20 | candidate signal; CI `[0.00, 0.50]`; only 4/5 noisy traces applicable |
| Spreadsheet N3, all-applicable confirmation | 5 / 3 / 10 | 0.60 | 0.40 | 0.40 | 0.00 | 5/5 applicable, but both arms reverse evolved; signal not confirmed |
| OfficeQA N1 | 1 / 1 / 2 | 0.50 | 0.50 | 0.50 | 0.00 | parser floor repaired; both arms rejected the update |
| OfficeQA N4 expanded | 3 / 3 / 5 | 0.80 | 0.80 | 0.80 | 0.00 | 3/3 mutations applicable; both arms rejected the update |
| WebShop N1 | 1 / 1 / 2 | 0.50 | 0.50 | 0.50 | 0.00 | non-floor evaluation; three candidates rejected in each arm |
| WebShop N3 integration smoke | 1 / 1 / 2 | 0.00 | 0.00 | 0.00 | 0.00 | mutation applicable, but efficacy invalid because of zero floor |
| SkillLearnBench N3, poem family | 1 / 0 / 2 | 0.50 | 0.00 | 0.00 | 0.00 | both arms reverse evolved; full held-out seed/clean/noisy = 0.25/0/0 |
| SkillLearnBench N3, weighted GDP family | 1 / 0 / 2 | 0.00 | — | — | — | stopped as a seed-calibration failure; not an efficacy result |

The two Spreadsheet runs used the same frozen test IDs, but separate model calls
changed the seed score from `0.50` to `0.60` and changed both evolved outcomes.
This is direct evidence that a single API run is insufficient for candidate
promotion. In the confirmation run, the clean and noisy SkillOpt artifacts were
different and each accepted one update, so the null gap is not an evaluation
cache artifact.

OfficeQA's current null result has a different cause: all three seed/clean/noisy
skill hashes are identical in the expanded N4 run because both proposed changes
were rejected. WebShop similarly adopted no new skill. SkillAdaptor's wall-clock
metadata is now removed from frozen skill-bank artifacts so rejected/no-op banks
receive the same semantic file hash and can reuse evaluation safely.

## Baseline deployment status

| Baseline | Domain | DeepSeek API path | Native smoke status | Remaining efficacy blocker |
|---|---|---|---|---|
| SkillOpt | Spreadsheet | OpenAI-compatible provider, thinking disabled | paired train/eval and N3/N4 hooks run | stochastic reverse evolution; candidate gap needs replication |
| SkillOpt | OfficeQA | same provider; bounded JSON control-character repair | native multi-document train/eval runs without systemic parsing failure | update gate is a no-op on current small split |
| SkillLearn self/teacher feedback | Skill Learning | project DeepSeek client; bounded tool-JSON recovery | Docker execution, verifier, N3/N4 replay path run | current families are clean-reverse or seed-floor |
| SkillAdaptor | WebShop | first-party DeepSeek adapter; eight-step episode horizon | paired WebShop evolution/evaluation and runtime hook run | no candidate skill adopted on current smoke split |

Incremental baseline changes are captured under `patches/baselines/` rather than
requiring the benchmark consumer to use the current dirty external checkouts.

## Token accounting

The selected Core-1 design/calibration runs in this report consumed 2,575,086
billed tokens across 882 observed calls: 2,286,705 prompt and 288,381 completion
tokens. Deduplication uses ledger event IDs. The total includes interrupted and
blocked SkillLearn family searches, because those calls were billed even though
they did not yield an efficacy result.

| Domain | Billed tokens |
|---|---:|
| Spreadsheet | 384,316 |
| Document QA | 701,277 |
| Interactive | 355,773 |
| Skill Learning | 1,133,720 |
| **Total** | **2,575,086** |

The new seed gate and SkillAdaptor semantic artifact hashing directly address
the two largest avoidable cost modes observed here: running evolution after a
known floor, and reevaluating no-op artifacts that differ only by timestamps.

## Next validation round

1. Run a cheap seed-only calibration across several structurally selected
   SkillLearnBench families and WebShop goals. Freeze only a validation pool
   with mixed seed outcomes; do not inspect noise outcomes during selection.
2. For OfficeQA and WebShop, enlarge the validation set enough that the native
   baseline accepts at least one clean update before testing a noise stage.
3. For Spreadsheet N3, run at least three independent paired repetitions on the
   now all-applicable split. Promote it only if clean evolution is non-degrading
   and the clean-minus-noisy direction repeats.
4. Screen one stage at a time per domain. Do not run an N1×N2×N3×N4 Cartesian
   product. A domain keeps only the stages that pass all promotion gates.
5. After operator promotion, freeze the larger benchmark split and run the
   common harness over every comparison method. Only this later phase supports
   the paper's final claim that existing methods degrade while the proposed
   robust-evolution pipeline improves on noisy and clean benchmarks.

## Evidence paths

- Core-1 definition: `benchmark/core1/README.md`
- N3/N4 public contract: `docs/core1-runtime-evidence-interface.md`
- Spreadsheet candidate signal:
  `outputs/runs/core1-spreadsheet-n3-expanded/20260813T103149516404Z-skillopt/result.json`
- Spreadsheet confirmation:
  `outputs/runs/core1-spreadsheet-n3-applicable-confirm/20260813T104512125192Z-skillopt/result.json`
- OfficeQA N4 expanded:
  `outputs/runs/core1-officeqa-n4-expanded/20260813T102616526997Z-skillopt/result.json`
- WebShop N1:
  `outputs/runs/core1-screen-smoke-webshop-n1-structural/runs/interactive--webshop--N1/20260813T101255959755Z-skilladaptor/result.json`
- SkillLearnBench poem-family N3:
  `outputs/runs/core1-screen-smoke-skilllearn-n3-fixed2/runs/skill_learning--skilllearnbench--N3/20260813T085057778905Z-skilllearn_self_feedback/result.json`
