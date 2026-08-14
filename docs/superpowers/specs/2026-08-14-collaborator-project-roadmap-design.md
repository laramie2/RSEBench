# Collaborator Project Roadmap Document Design

Date: 2026-08-14

## Objective

Create one Chinese-language entry document for repository collaborators at
`docs/project-roadmap.md`. The document must let a new contributor answer four
questions without reconstructing the project from historical plans:

1. Which benchmarks and baselines are in the current executable scope?
2. What do N1, N2, N3, and N4 change in each benchmark?
3. What evidence is required before a benchmark cell or noise operator advances?
4. What implementation and experimental work remains?

The document is an execution guide, not a replacement for the detailed design
specifications, machine-readable registries, experiment reports, or benchmark
card.

## Audience and authority

The primary audience is a repository collaborator who understands agent
evaluation but has not followed the local validation history. The document uses
concise research terminology, tables, explicit status labels, and repository
links rather than narrating every pilot run.

The current Core-1 scope is authoritative:

| Domain | Benchmark | Primary clean/noise validation baseline |
|---|---|---|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt |
| Document QA | OfficeQA Full | SkillOpt |
| Interactive | WebShop | SkillAdaptor |
| Skill learning | SkillLearnBench | separated-round self-feedback; teacher-feedback for N4 |

Mathematics, DocVQA, WikiTableQuestions, SearchQA, SealQA, SkillsBench,
SkillFlow-Task, and other historical candidates are not current Core-1
commitments. They appear only in a clearly marked extension appendix.

When sources differ, the document applies this precedence order:

1. active entries in `benchmark/registry/` and executable experiment YAML;
2. the unified clean-v2 release design and Core-1 runtime contract;
3. the frozen Core-1 operator specification and manifests;
4. dated validation reports;
5. the early project-wide design, used only for long-term intent.

This prevents an early proposal from overriding a later frozen configuration.

## Deliverable structure

The final document uses an execution-manual structure.

### 1. Project purpose and research claim

Explain that RSEBench evaluates the complete self-evolution loop, not only
noisy inference. State the intended comparison between a seed skill, a skill
evolved on clean evidence, and a skill evolved on noisy evidence, all evaluated
on untouched held-out data. Separate intended hypotheses from demonstrated
results.

### 2. Current Core-1 benchmarks

For each of the four benchmarks, describe:

- the task and verifier;
- the unit of evolution;
- the current clean-v2 acquisition/validation/test scale;
- the primary baseline;
- why the domain contributes a distinct self-evolution failure mode.

The clean-v2 scale is taken from `configs/experiments/clean-v2.yaml`, while
Core-1 noise-screen scales are identified separately as pilot scales. The two
must not be merged into one table without labels.

### 3. Baseline methods and status tiers

Use three tiers:

- **Current reference baselines:** SkillOpt, SkillAdaptor, SkillLearnBench
  self-feedback, and SkillLearnBench teacher-feedback for N4.
- **Planned comparison baselines:** Trace2Skill, SkillGrad, EvoSkill,
  RethinkSkill, Skills-Coach, SkillFlow, and FederatedSkill. Each entry states
  its native domain, update mechanism, and current inactive/adaptation status.
- **Non-executable reference:** CoEvoSkills, marked paper-only until runnable
  code or an explicitly labeled reimplementation exists.

The section must distinguish native reproduction, compatibility patches, and
unified-harness adaptation. It must not imply that an inactive registry entry
has completed a formal run.

### 4. N1–N4 noise model

Define the stages by their location in the learning pipeline:

```text
task instance -> environment interaction -> stored trajectory -> update feedback
      N1                  N2                     N3                 N4
```

- N1 changes task-side context before the first action.
- N2 changes execution-visible evidence or observation sources.
- N3 changes the stored trajectory after execution/reward and before
  reflection.
- N4 changes reflection, critique, or fault attribution before skill update.

State that N1/N2 are static paired artifacts, N3/N4 are deterministic runtime
mutations with replay packs, and the four stages are independent experimental
arms rather than a Cartesian composition. All current Core-1 operators use one
L2 mutation with fail-closed applicability reporting.

### 5. Four-domain noise matrix

Include a 4 x 4 table populated from the active Core-1 YAML files. Each cell
must name both the concrete operator and the protected information that remains
unchanged. This is the central reference table for collaborators implementing
or reviewing noise adapters.

### 6. Experimental workflow and promotion gates

Show the stage barrier:

```text
baseline bootstrap and identity verification
-> clean engineering readiness
-> clean efficacy readiness
-> immutable clean release
-> independent N1-N4 validation
-> benchmark freeze
-> comparison baselines and RGSE
```

Document the clean-v2 cell rules exactly:

- engineering readiness requires at least two of three fixed method seeds to
  produce an accepted, semantically changed, non-degrading artifact without a
  systemic execution failure;
- efficacy readiness additionally requires strictly positive clean gain in at
  least two of three seeds;
- N1-N4 remain locked until every required Core-1 cell is efficacy-ready.

Noise promotion then requires validity, seed calibration, applicability, a
real clean update, a clean-minus-noisy effect on untouched clean test data, and
replication. Null, opposite, blocked, and inapplicable outcomes remain in the
denominator or are reported under their typed status as required by the
protocol.

### 7. Current status and known limitations

Provide a date-stamped status block and link to detailed reports. It must
separate:

- execution/interface readiness;
- ability to accept an update;
- positive clean efficacy;
- stable noise efficacy.

The document must not claim that all four cells are ready merely because their
processes launch. Volatile live-run numbers belong in dated reports or frozen
release summaries, not in the timeless benchmark definition.

### 8. Contributor work plan

Organize work by dependency rather than by repository directory:

1. finish and freeze clean-v2 evidence;
2. repair and rerun only cells invalidated by typed interface failures;
3. obtain the required clean engineering and efficacy readiness;
4. validate N1 one domain at a time, then N2-N4 independently;
5. freeze promoted operators, manifests, hashes, replay packs, and reports;
6. activate comparison baselines by native-domain priority;
7. implement and evaluate RGSE only after the benchmark freeze;
8. run final multi-seed, paired, cost-accounted experiments and publish the
   benchmark card.

Each phase names its acceptance evidence and the changes that invalidate prior
results. The checklist also states prohibited shortcuts: selecting final-test
samples by observed outcome, retuning noise after test observation, modifying
baseline core algorithms without disclosure, dropping zero-update seeds, or
committing secrets/raw run directories.

### 9. Reproducibility and repository map

Link collaborators to registries, baseline patch series, clean manifests,
Core-1 configs, runtime evidence interface, compact releases, result contracts,
and the unified CLI. Explain that external baseline clones, raw datasets,
trajectories, token ledgers, and secrets are local/gitignored artifacts.

### 10. Candidate extensions

List inactive benchmarks and methods by their evidence status. Label them as
future candidates, not blockers for Core-1. State the activation rule: a new
benchmark requires a reliable verifier, frozen split, at least two credible
method intersections or explicitly adapted baselines, and the same clean/noise
qualification contract.

## Style and maintenance rules

- Write in Chinese; preserve official benchmark, method, schema, and metric
  names in English.
- Prefer tables and short definitions over historical narration.
- Use relative repository links so GitHub renders the document correctly.
- Mark status with explicit terms such as active, inactive, candidate,
  blocked, diagnostic, or paper-only.
- Never describe a hypothesis, pilot signal, or one-family result as a stable
  benchmark conclusion.
- Point detailed numeric results to dated reports; update the roadmap only when
  scope, gates, or frozen release state changes.
- Do not include credentials, machine-specific paths, or links to gitignored
  outputs as the only evidence for a public claim.

## Verification

Before committing the final document:

1. check every active benchmark, method, repository revision, operator, and
   sample count against the registry or executable YAML;
2. verify all 16 Core-1 operator cells are represented exactly once;
3. scan for contradictions between current and extension scope;
4. scan for placeholders and unsupported completion claims;
5. validate every relative repository link;
6. run the relevant documentation/registry tests and the repository test suite
   required by the current branch policy.

## Acceptance criteria

The document is complete when a collaborator can identify the active four-domain
matrix, understand every N1-N4 injection point, distinguish current and planned
baselines, follow the stage gates, select the next unblocked task, and find the
machine-readable source for every operational claim.
