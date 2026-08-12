# Baseline–Benchmark Usage and Intersection Audit

Date: 2026-08-12

This audit is based on the pinned local repositories, not only paper-level name
matching. “Native” means the checkout contains a loader/evaluator/launch path for
the benchmark. “Adapted” must be reported separately in later unified-harness
experiments.

## Actual native intersections

| Domain or diagnostic lane | Benchmark | Native methods in the downloaded snapshots | Intersection status |
|---|---|---|---|
| Spreadsheet operations | SpreadsheetBench Verified | Trace2Skill, SkillOpt, SkillGrad | strong: three methods |
| Document retrieval QA | OfficeQA | SkillOpt, EvoSkill | usable: two methods |
| Document visual QA | DocVQA | SkillOpt | no two-method native intersection |
| Search/retrieval QA | SearchQA | SkillOpt | no two-method native intersection |
| Grounded agent QA | SealQA | EvoSkill | no two-method native intersection |
| Mathematics | LiveMathematicianBench | SkillOpt | no two-method native intersection |
| Mathematics | DAPO / AIME | none of the downloaded evolution methods | calibration data only |
| Skill-native diagnostic | SkillsBench | CoEvoSkills paper artifact | method code unavailable in this checkout |
| Skill-native diagnostic | SkillFlow-Task | SkillFlow iterative SE, FederatedSkill | usable: two related runners |

The earlier assumption that Trace2Skill and SkillOpt both natively cover DAPO/AIME
is not supported by the downloaded code. DAPO remains useful for cheap text-only
noise calibration, but it cannot be the main native-baseline-overlap benchmark
without explicitly adapting at least two methods.

## How each method uses its benchmark

### Trace2Skill

The repository is a complete SpreadsheetBench pipeline. It runs a spreadsheet
agent, saves trajectories, applies official-style cell-range scoring, converts
success/failure traces into analyses, and evolves a skill directory through
parallel error-driven or combined success/error updates. Its unit of evolution is
a reusable spreadsheet skill, while task outputs remain XLSX files. This makes it
a high-priority baseline for C1 prompt noise and C2 workbook noise.

### SkillOpt

SkillOpt exposes one trainer and environment adapters. A target model executes
tasks; evaluation traces are grouped into minibatches; an optimizer analyzes
failures and edits a skill under selection/gating. Its checkout includes native
configs and fixed split metadata for SpreadsheetBench, OfficeQA, DocVQA, SearchQA,
and LiveMathematicianBench. SpreadsheetBench uses workbook execution and the
official cell comparator. OfficeQA uses an offline document/search tool runtime and
the released reward logic. DocVQA is a one-turn image task. The model router can
support OpenAI-compatible endpoints internally, but the current launcher does not
offer a first-class `deepseek` backend, so a small reviewed adapter is required
before Pilot-B.

### SkillGrad

SkillGrad is SpreadsheetBench-only in the released integration. It treats the
structured skill package as the parameter: executor trajectories become
per-example textual gradients, a momentum agent accumulates recurring signals, and
a patcher performs layer-aware edits. The documented split is 200 evolution / 200
held-out, with a default 40-task training subset. It is the third native spreadsheet
baseline and should be included after the first two Pilot-B smoke runs.

### EvoSkill

EvoSkill evolves a skill or base prompt using a frontier and repeated evaluation.
The checkout contains a self-contained OfficeQA demo (10 questions, 9 documents)
and SealQA scripts/scorer. The OfficeQA demo uses train/validation ratios and a
multi-tolerance scorer. It remains useful for native reproduction; the formal
246-question OfficeQA data and corpus are now downloaded, so the next requirement
is a reviewed adapter that preserves EvoSkill's algorithm while consuming the
shared formal manifest.

### Skills-Coach

Skills-Coach generates training/test tasks for an input skill, evaluates multiple
rollouts, extracts advantages, and retains an optimized skill only when its
multi-dimensional criteria improve. It does not natively use the selected fixed
domain benchmarks. Treat it as a mechanism baseline on skill-native tasks, not as a
native SpreadsheetBench/OfficeQA baseline.

### CoEvoSkills

The repository documents generator/verifier co-evolution and reports SkillsBench
results, but explicitly marks code as “coming soon” and contains paper/site assets
rather than a runnable method implementation. It can be discussed and its reported
numbers cited, but it cannot be included as an executable baseline until code is
released or independently reproduced.

### FederatedSkill and SkillFlow

SkillFlow performs iterative shared-skill evolution over ordered professional task
families in Harbor containers. FederatedSkill adds client-specific libraries and a
cloud merger over the same task format. Each task supplies an instruction,
environment, reference solution, and executable verifier; the family ordering
creates the evolution trajectory. These methods are appropriate for the
skill-native diagnostic lane, not as same-scale replacements for domain QA.

## Mathematics recommendation

Use DAPO-1000 now for Pilot-A execution sensitivity because it is text-only,
deterministic, cheap, and directly supported by `deepseek-v4-flash`. Do not freeze it
as the paper’s main math self-evolution benchmark yet. Before freeze, choose one of:

1. adapt two common method interfaces to DAPO and report them as adapted baselines;
2. use LiveMathematicianBench as SkillOpt-native data and adapt one additional method;
3. replace the math lane with another reasoning domain only after finding a genuine
   two-method native intersection.

The benchmark paper should maintain separate columns for native reproduction and
unified-harness adaptation so the comparison remains auditable.

## Skill-native data format and distribution

### SkillsBench

SkillsBench contains 87 standard tasks and 14 `tasks-extra` tasks. A standard task
is a BenchFlow package:

```text
task.md                 YAML front matter + natural-language instruction
environment/            Dockerfile, inputs, and task-bound skill packages
oracle/solve.sh          reference execution
verifier/test.sh         verifier entry point
verifier/test_outputs.py output assertions
```

The 87 standard tasks contain 232 task-bound skill packages: 23 tasks have one
skill, 23 have two, 20 have three, 9 have four, 6 have five, 5 have six, and 1 has
seven. Difficulty is 6 easy / 53 medium / 28 hard. Categories are 16 software
engineering; 14 each industrial/physical, office/white-collar, and natural science;
9 finance/economics; 8 mathematical/formal; 7 cybersecurity; and 5 media/content.
Metadata is multi-label: the largest modalities are JSON 27, source code 24, CSV 19,
time series 15, spreadsheet 14, and PDF 12. This makes task–skill pairing, skill
composition count, modality, and verifier type natural stratification axes.

Recommended diagnostic perturbations are: skill-name/description ambiguity;
irrelevant skill insertion; relevant-skill omission; duplicated/stale skill version;
skill-order perturbation; conflicting reference files; and verifier-feedback
dropout. Report selection accuracy, composition accuracy, execution pass rate, and
skill utilization separately.

### SkillFlow-Task

SkillFlow-Task is fully downloaded: 20 families, 166 tasks, 2,656 repository files,
and 1.67 GB. Each task has:

```text
task.toml               metadata, resource limits, timeouts, image ID
instruction.md          task prompt
environment/            Dockerfile and input artifacts
solution/               reference output and solve script
tests/                  executable verifier files
```

Families contain 8 or 9 ordered tasks. Difficulty labels are 4 easy, 102 medium,
56 hard, 3 medium-hard, and 1 expert. Inputs are strongly office-oriented: 128 XLSX,
120 JPG, 105 CSV, 42 JSON, 31 PDF, 28 TSV, 16 PPTX, and 8 HWPX files in task
environments. Most tasks begin without task-local skills (140/166); later skill
state is accumulated across the family. That temporal structure supports noise on
skill transfer, stale library state, cross-task contamination, feedback sparsity,
and family/task reordering.
