# Current Noise and Baseline Deployment Status

Date: 2026-08-12

## Executive status

All currently selected datasets and nine method or diagnostic repositories are
downloaded and pinned. Four baseline environments are executable locally:
Trace2Skill, SkillOpt, SkillGrad, and EvoSkill. SkillFlow is additionally
installed and can plan a real eight-task family after pinning its Harbor
dependency, but its container image and DeepSeek worker adapter are not ready.

Only SpreadsheetBench prompt noise currently has evidence of an execution-level
effect on evolved skills. The OfficeQA, DocVQA, and artifact-level spreadsheet
operators have passed construction and label-preservation checks but have not yet
passed effectiveness gates. The first DAPO rule-noise execution pilot completed
and was rejected because its aggregate effect was zero. No GPT-5.5 call was used;
all new online checks used `deepseek-v4-flash`.

## Noise results by domain

| Domain | Construction result | Execution/evolution evidence | Current decision |
|---|---|---|---|
| Spreadsheet/Table | 10 tasks × three operators: 30/30 structurally accepted | Earlier 50-task reproductions show lower evolved final scores under prompt noise; new Trace2Skill clean skill smoke is 1/1 official-correct | Prompt noise remains a candidate; workbook noise still needs paired execution |
| Document QA | Formal OfficeQA 10 tasks × three operators: 30/30 accepted | No clean/noisy model execution or self-evolution comparison yet | Feasible to construct, not yet shown effective |
| Visual document QA | DocVQA: 20 prompt variants accepted; 10 image-clutter variants not applicable because answer boxes are absent | Not executed: DeepSeek V4 Flash is text-only | Keep prompt lane; block visual lane until a separately approved vision model exists |
| Mathematics | DAPO: five rule variants accepted; model-backed flawed partial solutions 0/5 accepted | Five-task clean/L1/L2/L3 rule-noise pilot had clean=noisy=0.6 at every severity | Reject current failed-attempt operator for minimum effect; redesign a subtler operator |
| Skill-native diagnostic | SkillsBench and SkillFlow formats/distributions audited | No skill-noise generation or execution yet | Mechanism lane only; implement after main-domain Pilot-B |

### Spreadsheet prompt-noise reproduction

The legacy 50-task runs should be read using two distinct metrics. `after` is the
evolved-skill final score, while `after - before` is the actual self-evolution
gain.

| Method | Clean before→after | Noisy evolved final range | Noisy evolution-gain range | What is established |
|---|---:|---:|---:|---|
| SkillOpt | 17→36, gain +19 | 25–34 | +11 to +21 | Final performance drops by 2–11 points; evolution-gain degradation is operator-dependent |
| SkillGrad | 21→42, gain +21 | 31–41 | +15 to +21 | Final performance drops by 1–11 points; evolution gain drops by 0–6 points |

These runs support prompt-noise feasibility, especially the model-generated P1
and P2 variants. They do not yet demonstrate reverse evolution, and the rule P1/P2
SkillOpt gains are not weaker than the clean gain. Future result tables must always
report clean/noisy initial score, evolved score, evolution gain, and
`clean_gain - noisy_gain` separately.

### New DAPO execution pilot

The reproducible run is:

```text
outputs/runs/pilot-a/20260812T082228672656Z-dapo-failed-attempt
```

It used five frozen tasks and 20 paired calls under clean/L1/L2/L3. The validated
scores were 0.6/0.6/0.6/0.6, so the L2 effect was 0 and the `minimum_effect` gate
failed. At the paired-task level there was one clean-correct→noisy-wrong flip and
one clean-wrong→noisy-correct flip; the remaining three tasks did not change.
This shows instability but no aggregate degradation.

An earlier thinking-enabled attempt is retained as a failed run at
`outputs/runs/pilot-a/20260812T081008661040Z-dapo-failed-attempt`: one task's four
conditions exhausted the 8192-token reasoning budget and returned empty content.
The execution pilot now uses the explicit non-thinking, 2048-token profile and a
new cache namespace. The corrected run completed all conditions using 25,088
tokens.

The model-generated `flawed_partial_solution` operator also failed feasibility:
all five candidates were rejected by answer-leak, invalid-JSON, or critic-consensus
gates. This is the correct failure behavior; the gates must not be weakened merely
to populate the benchmark.

## Baseline deployment matrix

Deployment levels are intentionally separate: repository, environment/CLI,
DeepSeek transport, clean benchmark execution, and self-evolution execution.

| Baseline | Repository | Environment/CLI | DeepSeek transport | Native clean execution | Self-evolution run | Next blocker |
|---|---|---|---|---|---|---|
| Trace2Skill | pinned | ready | real request passed | SpreadsheetBench skill-preloaded smoke 1/1 official-correct | not run | freeze a clean-solvable pilot subset, then clean/noisy trace collection |
| SkillOpt | pinned | ready; 60 backend tests pass | native `openai_compatible` request passed | not yet run | not run | materialize the same shared pilot manifest in its environment adapter |
| SkillGrad | pinned | ready | native chat-completions route passed | not yet run | not run | map shared SpreadsheetBench manifest and result paths |
| EvoSkill | pinned | ready; CLI and bundled Harbor 0.6.1 start | not configured for direct DeepSeek | OfficeQA demo not yet rerun | not run | add a reviewed DeepSeek-capable harness and formal OfficeQA adapter |
| SkillFlow | pinned | ready after Harbor pin; eight-task dry-run passes | not configured | dry-run only | not run | build the large base image, add DeepSeek worker, then run one task/family |
| FederatedSkill | pinned | not installed | not configured | not run | not run | deploy only after the SkillFlow single-worker lane is stable |
| Skills-Coach | pinned | not installed | Anthropic-oriented release | no selected native domain benchmark | not run | use later as a skill-native mechanism baseline or add an explicit adapter |
| CoEvoSkills | pinned artifact repo | no method code | unavailable | unavailable | unavailable | upstream code is marked coming soon; report-only until release |
| SkillsBench | pinned benchmark repo | data audited | not applicable by itself | not run | not an evolution method | use as diagnostic benchmark, not as a method baseline |

The Trace2Skill smoke also ran the same task without preloaded skills: the runner
completed, but the official score was 0/1. With the native preloaded spreadsheet
skill it scored 1/1. This makes the task usable for a tiny skill-effect smoke, but
one task is not evidence of benchmark-level performance.

SkillFlow originally resolved an unpinned current Harbor 0.21.0 and failed because
`TaskPaths.is_valid` had been removed. Pinning Harbor to commit
`ab6c8f07914f3f4c24b52377475d90f506103844` installs Harbor 0.6.6 and restores the
repository's expected API; its dry-run then planned all eight tasks in the
Compensation-Scenario-Modeling family successfully.

## Immediate experiment order

1. Select 5–10 SpreadsheetBench tasks that both Trace2Skill and SkillOpt solve in
   the clean setting; execute paired clean, prompt-noisy, and workbook-noisy runs.
2. Run the same fixed OfficeQA mini-manifest with SkillOpt and EvoSkill only after
   both reproduce non-floor clean scores.
3. Redesign math noise as a locally correct, high-similarity derivation with one
   hidden pivotal error; regenerate through hard leakage and critic gates before a
   second execution pilot.
4. Implement skill-selection and stale-skill perturbations on a stratified subset
   of SkillsBench/SkillFlow only after the two main-domain lanes are operational.
5. Do not launch full self-evolution until the clean-solvable screening, frozen
   split, and shared result schema are identical across methods.

## Verification

The RSEBench harness currently passes 67 tests with 88% line coverage. The new
non-thinking execution-profile tests pass, SkillOpt's focused backend suite passes
60 tests, and Trace2Skill's clean skill smoke was scored by its official-compatible
cell evaluator rather than runner success alone.
