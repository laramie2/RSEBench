# DeepSeek API Baselines and Paired Evolution Validation Design

Date: 2026-08-12

## Objective

Adapt every runnable baseline to use `deepseek-v4-flash` through the DeepSeek API,
prove each adapted execution path with a bounded smoke test, and then validate
noise on three domains by evolving from the same seed skill on paired clean and
noisy evolution data. Both evolved skills are evaluated only on the same frozen
clean test split.

Earlier SpreadsheetBench results that only applied noise at final-skill evaluation
are excluded from effectiveness claims. They may be retained as historical
artifacts, but they do not decide whether an operator enters the benchmark.

## Scope

### Runnable methods

- Trace2Skill
- SkillOpt
- SkillGrad
- EvoSkill
- Skills-Coach
- SkillFlow
- FederatedSkill

CoEvoSkills is report-only because its downloaded repository has no executable
method implementation. SkillsBench is a diagnostic benchmark, not an evolution
method.

### Priority domains

| Domain | Dataset | Primary methods |
|---|---|---|
| Spreadsheet operations | SpreadsheetBench-Verified | Trace2Skill, SkillOpt, SkillGrad |
| Document QA | formal OfficeQA | SkillOpt, EvoSkill |
| Mathematics | DAPO fixed pilot subset | SkillOpt, EvoSkill adapted lane |

DAPO is a validation dataset rather than a frozen final paper choice. If neither
method obtains positive clean evolution gain, the math lane moves to
LiveMathematicianBench or AIME without changing the paired protocol.

## Invariants

1. The only online model is exactly `deepseek-v4-flash` at
   `https://api.deepseek.com`.
2. Credentials are loaded from the project-root `.env`; they are never copied to
   run artifacts, command output, patches, or baseline repositories.
3. No provider/model fallback is allowed.
4. Generation, optimizer, target, worker, verifier-critic, and merger model calls
   are all recorded by role.
5. The clean and noisy arms start from byte-identical seed skills.
6. The two arms use identical task IDs, split membership, task order, method seed,
   model settings, iteration count, token budget, and tool budget.
7. Only the evolution-train and evolution-validation views differ. Final
   evaluation always uses the same untouched clean-test tasks.
8. Clean-test outputs never enter reflection, skill updates, frontier selection,
   early stopping, or hyperparameter decisions.
9. Noise hard gates are not weakened to obtain an apparent performance drop.
10. Runner success is not task success; every task must use its benchmark scorer.

## Architecture

### Provider capability layer

Extend `rsebench.providers.deepseek` behind a small capability interface:

- chat completion;
- JSON response validation;
- OpenAI-compatible tool calling;
- explicit non-thinking requests by default;
- immutable content-addressed cache;
- bounded retry and timeout policy;
- per-call role, usage, latency, finish reason, and error metadata;
- redacted diagnostics.

The provider remains transport-only. It must not know about a baseline algorithm
or benchmark.

### Tool agent

Add a reusable DeepSeek API tool loop for baseline paths that previously delegated
execution to Claude Code, OpenCode, Qwen Code, or another CLI. The initial tool set
is deliberately small:

- list files under an allowed workspace;
- read a bounded text file;
- write a file under the workspace;
- run a bounded subprocess in the workspace;
- report a final answer.

Path containment, command timeout, maximum turns, maximum output characters, and
an allowlisted working root are enforced by the harness. Harbor-backed methods use
the same model loop but bind tool execution to the Harbor environment rather than
the host filesystem.

### Baseline adapters

Each method adapter declares:

- upstream commit;
- model roles it uses;
- native environment/config mapping;
- clean task command;
- one-update evolution command;
- expected skill artifact;
- task result path and scorer;
- unsupported capabilities or remaining blockers.

Native OpenAI-compatible backends are preferred. A thin compatibility adapter is
added only when the method lacks one. The baseline's evolution algorithm, prompts,
selection logic, and benchmark scorer remain unchanged unless an incompatibility
is explicitly documented.

### Experiment manifests

Create immutable manifests for:

- task split and order;
- clean/noisy pair mapping;
- noise specification and validation hashes;
- seed skill hash;
- baseline configuration;
- model roles and budgets;
- run arm (`clean` or `noise`);
- produced skill hash;
- per-task clean-test outcomes.

Every run directory is append-only and has a unique ID. Cached model responses may
be reused only when the full request configuration and role match.

## Baseline adaptation strategy

| Method | Adaptation |
|---|---|
| Trace2Skill | Configure its native OpenAI-compatible client for every executor, analysis, and evolution call; add manifest/result wrappers only. |
| SkillOpt | Use its native `openai_compatible` target and optimizer backends; expose role-specific DeepSeek settings through the shared launcher. |
| SkillGrad | Use its chat-completions model family and DeepSeek endpoint; remove the Azure-specific naming assumption in the adapter without changing training logic. |
| EvoSkill | Add a DeepSeek API harness backed by the reusable tool agent, plus CSV environments for OfficeQA and DAPO. |
| Skills-Coach | Route task generation, optimization, comparative execution, and judging through the shared provider/tool agent. Smoke-test on its native generated-task flow; do not include it in the three main-domain pilots. |
| SkillFlow | Add a Harbor agent that obtains actions through the shared DeepSeek provider. Pin its compatible Harbor release and smoke one task before an iterative family run. |
| FederatedSkill | Reuse the SkillFlow DeepSeek worker and route cloud merge through DeepSeek. Smoke only after the single-worker SkillFlow path passes. |

## Smoke-test ladder

Each runnable baseline receives a machine-readable status for five levels:

1. `transport`: exact model request returns a valid response.
2. `structured`: one schema-constrained JSON response validates.
3. `tool`: the model performs one file/tool operation in a temporary workspace.
4. `native_task`: one clean native task passes the official scorer.
5. `evolution`: 2–4 evolution examples produce a changed skill artifact and a
   completed evaluation record.

The main-domain paired experiment may use a method only after levels 1–5 pass for
that domain. Failures are recorded, not silently skipped.

## Paired data protocol

For each domain, freeze group-isolated splits:

- `evolution_train`
- `evolution_validation`
- `clean_test`

The clean and noisy views share task IDs and gold labels. Noise is injected only
into the first two views and is marked `timing=evolution`. The clean test view is
never transformed.

The initial validation budget is:

- 20 evolution-train tasks;
- 10 evolution-validation tasks;
- 30 clean-test tasks;
- 1–2 method-native update iterations;
- two independent method seeds;
- one operator per comparison.

If a benchmark or method cannot support that size, use the largest stratified size
that preserves all three splits and record the deviation. Operators showing a
consistent signal graduate to 40/20/50 tasks and three seeds.

## Noise operators

### SpreadsheetBench

- C1 failed-attempt or relevant misleading operation history;
- C2 semantic-decoy sheet;
- C2 stale backup sheet or similar-column artifact.

### OfficeQA

- C1 plausible but wrong retrieval/source hint;
- C2 semantic-decoy document;
- C2 gold-rank displacement with answer-free decoys.

### DAPO

- C1 high-similarity partial derivation with one pivotal hidden error;
- C2 a locally valid but globally inapplicable theorem/example;
- optional feedback-noise pilot only after the first two pass.

The existing explicit rule `failed_attempt` is rejected for DAPO because its
paired Pilot-A effect was zero. The model-generated math operator must pass JSON,
answer-leak, exactly-one-error, and two-critic consensus gates before execution.

## Outcomes and gates

For method `m`, define:

```text
clean_gain(m) = score(clean_evolved_skill, clean_test)
              - score(seed_skill, clean_test)

noisy_gain(m) = score(noise_evolved_skill, clean_test)
              - score(seed_skill, clean_test)

evolution_gap(m) = clean_gain(m) - noisy_gain(m)
```

The primary comparison is
`score(clean_evolved_skill, clean_test) > score(noise_evolved_skill, clean_test)`.

An operator graduates from the validation pilot when:

- clean evolution gain is positive;
- the evolution gap is at least 0.05 absolute score;
- both method seeds have the same direction;
- the effect is not explained by API, tool, or evaluator failure;
- at least two methods in the domain show the same direction.

`noisy_gain < 0` is separately reported as reverse evolution. Failure to meet a
gate is a negative result and triggers operator redesign, not selective task
removal beyond the predeclared clean-solvable screening.

## Cost controls

- Use explicit non-thinking mode and the smallest role-appropriate token cap.
- Cache exact requests across interrupted runs.
- Run smoke levels serially and stop at the first failed level.
- Screen clean-solvable tasks before paired evolution.
- Start with one operator and two seeds; do not run operator combinations until a
  single operator graduates.
- Store token totals by method, role, domain, arm, and task.

## Verification and reporting

Unit tests cover provider request bodies, cache isolation, redaction, tool path
containment, manifest equality, pair construction, clean-test isolation, skill
hash changes, and metric calculation. Integration tests use fake model responses
and tiny fixtures. Online smoke outputs are retained separately from automated
tests.

The final pilot report contains:

- baseline adaptation and five-level smoke matrix;
- frozen split and pair hashes;
- noise generation/validation acceptance rates;
- seed, clean-evolved, and noise-evolved clean-test scores;
- clean/noisy gains and evolution gaps;
- token/error/tool-failure diagnostics;
- accepted, rejected, and redesigned operators.
