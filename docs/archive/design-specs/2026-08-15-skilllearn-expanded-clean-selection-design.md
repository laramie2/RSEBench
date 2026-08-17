# SkillLearn Expanded Clean Selection Design

## Goal

Expand the SkillLearn/self-feedback validation data from one task family to a
clean-only candidate pool, then freeze a multi-family subset whose baseline
self-evolution is reproducibly executable and beneficial before any N1–N4 run.

## Candidate pool

The pool contains eight existing `clean_qualification_v2` family manifests.
Each family keeps the official instance order: instances 1–2 are train,
instance 3 is validation, and the remaining 2–3 instances are clean test.

| Family | Category | Train | Validation | Clean test |
|---|---|---:|---:|---:|
| dependency-vulnerability-check | Software Engineering | 2 | 1 | 2 |
| enterprise-information-search | Information Retrieval | 2 | 1 | 3 |
| financial-analysis | Data & Analytics | 2 | 1 | 3 |
| github-repo-analytics | Software Engineering | 2 | 1 | 2 |
| offer-letter-generator | Productivity Tools | 2 | 1 | 3 |
| organize-messy-files | Utilities & Other | 2 | 1 | 3 |
| schedule-planning | Productivity Tools | 2 | 1 | 2 |
| stock-data-visualization | Data & Analytics | 2 | 1 | 2 |

The pool therefore contains 44 official instances: 16 train, 8 validation,
and 20 clean test. All instances resolve through committed portable locators
and the committed image manifest declares an existing prebuilt image for every
task.

## Execution contract

- Baseline: `skilllearn_self_feedback`.
- Provider/model: DeepSeek / `deepseek-v4-flash`.
- Method seeds: `20260813`, `20260814`, `20260815`.
- Two self-feedback evolution rounds per family/seed.
- Temperature 0, thinking disabled, maximum 4096 completion tokens and 16 tool
  turns.
- Exactly 24 clean units; no noise materialization or N1–N4 execution.
- At most three SkillLearn units run concurrently. Family/seed Docker resource
  keys keep mutable execution isolated.
- Every completed unit records run-, stage-, and task-level timing plus the
  provider token ledger.

## Selection and freeze rule

A family is eligible only if all three seeds complete with full official
verifier coverage, at least two seeds accept an update, at least two seeds have
strictly positive held-out clean gain, and the remaining seed is nondegrading.

Freeze at least four eligible families with a combined clean-test denominator
of at least ten. Selection first maximizes category coverage, then prefers a
three-instance clean test, and finally uses lexical family order as a
deterministic tie-break. Noise applicability and noise outcomes are excluded
from selection.

If fewer than four families qualify, do not freeze a smaller SkillLearn bundle
and do not weaken the rule. Report the completed clean evidence and screen
additional official families in a separate clean-only candidate round.

## Outputs

- Matrix: `configs/experiments/skilllearn-clean-expanded-v1.yaml`.
- Provider outputs: `outputs/runs/skilllearn-clean-expanded-v1-20260815/`.
- After completion, a machine-readable aggregate and Chinese report are
  generated from the fixed 24-unit denominator.
- The eventual frozen release contains exact ordered task IDs, source hashes,
  baseline/model identity, selected family names, and references to the clean
  artifacts used as controls for later N1–N4 comparisons.
