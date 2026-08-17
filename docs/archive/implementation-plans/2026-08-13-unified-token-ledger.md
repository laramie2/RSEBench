# Unified Token Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record and aggregate exact billed and logical token usage across every new RSEBench DeepSeek/SkillOpt experiment, and backfill only observable historical usage.

**Architecture:** A shared `rsebench.usage` package owns the event schema, per-process JSONL writer, context propagation, validation, aggregation, and historical audit. RSEBench's DeepSeek provider and SkillOpt's OpenAI-compatible backend emit the same event contract. Experiment orchestrators pass run/domain/benchmark/arm/stage context and write atomic summaries beside each run.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, JSONL, OpenAI-compatible DeepSeek API, existing SkillOpt subprocess harness.

## Global Constraints

- All online calls remain exactly `deepseek-v4-flash` at `https://api.deepseek.com` with thinking disabled.
- Default cost reporting uses `billed_tokens`; `logical_tokens` includes cache hits.
- Historical calls without provider usage are `unobservable`; no token estimates are permitted.
- Token artifacts contain no prompts, completions, tool payloads, raw error messages, API keys, or Hugging Face tokens.
- New per-call events are canonical; existing SkillOpt `_total` remains a compatibility diagnostic and must not be added to stage totals.
- Do not connect or execute an additional self-evolution baseline in this implementation.

---

### Task 1: Core event ledger and aggregator

**Files:**
- Create: `src/rsebench/usage/__init__.py`
- Create: `src/rsebench/usage/ledger.py`
- Test: `tests/usage/test_ledger.py`

**Interfaces:**
- Produces: `TokenUsageEvent`, `record_token_event(...)`, `token_context_environment(...)`, `aggregate_token_usage(...)`, and `write_token_usage_artifacts(...)`.
- Consumes: `rsebench.contracts.StrictModel` and standard-library JSON/path/threading utilities only.

- [ ] **Step 1: Write failing schema and accounting tests**

Create tests that construct observed success, cache-hit success, and unobservable
error events; assert negative counts and inconsistent totals fail validation.
Use this public surface:

```python
from rsebench.usage import (
    TokenUsageEvent,
    aggregate_token_usage,
    record_token_event,
    token_context_environment,
    write_token_usage_artifacts,
)

event = TokenUsageEvent(
    event_id="a" * 64,
    timestamp="2026-08-13T00:00:00+00:00",
    run_id="run-1",
    domain="math",
    benchmark="dapo_fixed_1000",
    arm="clean",
    stage="rollout",
    provider="deepseek",
    model="deepseek-v4-flash",
    prompt_tokens=10,
    completion_tokens=5,
    total_tokens=15,
    cache_hit=False,
    billed=True,
    usage_observed=True,
    status="success",
    source="test",
)
```

- [ ] **Step 2: Run the core tests and verify RED**

Run:

```bash
pytest -q tests/usage/test_ledger.py
```

Expected: collection fails because `rsebench.usage` does not exist.

- [ ] **Step 3: Implement the strict event and context contract**

Implement `TokenUsageEvent` with schema version
`rsebench.token-usage.v1`, enum-like `Literal` status, non-negative token fields,
and a model validator enforcing:

```python
if self.usage_observed and self.total_tokens != (
    self.prompt_tokens + self.completion_tokens
):
    raise ValueError("observed total_tokens must equal prompt plus completion")
if self.cache_hit and self.billed:
    raise ValueError("cache hits cannot be billed")
if self.status != "success" and self.usage_observed:
    raise ValueError("failed/interrupted calls cannot claim observed usage")
```

Implement `token_context_environment` as a pure function returning a copy of the
base environment with the six `RSEBENCH_TOKEN_*` fields populated.

- [ ] **Step 4: Implement process-sharded append-only writing**

`record_token_event` must return `None` when no ledger directory is configured.
Otherwise it reads explicit values before environment defaults, allocates a
process-local sequence under a threading lock, hashes the non-secret event
identity, validates the event, and appends exactly one JSON object plus newline
to `events/<pid>.jsonl`.

Use a module-level lock around sequence allocation and append so worker threads
cannot interleave JSON records. Do not use prompt or response content in the
event identity.

- [ ] **Step 5: Implement deduplicating aggregation and atomic artifacts**

`aggregate_token_usage(ledger_dir)` must:

```python
{
    "schema_version": "rsebench.token-summary.v1",
    "attempted_calls": 3,
    "successful_calls": 2,
    "observed_calls": 2,
    "unobservable_calls": 1,
    "cache_hit_calls": 1,
    "observed_coverage": 2 / 3,
    "billed_tokens": {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    },
    "logical_tokens": {
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
    },
    "groups": {
        "domain": {"math": {}},
        "benchmark": {"dapo_fixed_1000": {}},
        "arm": {"clean": {}},
        "stage": {"rollout": {}},
        "model": {"deepseek-v4-flash": {}},
        "status": {"success": {}},
        "source": {"test": {}},
    },
}
```

Each group leaf uses the same call counters and billed/logical token structures.
Identical duplicate IDs are counted once. Conflicting duplicate IDs and malformed
JSON fail. `write_token_usage_artifacts` writes `summary.json` and `report.md`
through sibling temporary files followed by `Path.replace`.

- [ ] **Step 6: Verify GREEN and commit the core ledger**

Run:

```bash
pytest -q tests/usage/test_ledger.py
git diff --check
git add src/rsebench/usage tests/usage/test_ledger.py
git commit -m "feat: add append-only token usage ledger"
```

Expected: all ledger tests pass.

---

### Task 2: Instrument the shared DeepSeek provider

**Files:**
- Modify: `src/rsebench/providers/deepseek.py`
- Modify: `tests/providers/test_deepseek.py`

**Interfaces:**
- Consumes: `record_token_event` from Task 1.
- Produces: one canonical event for provider success, cache success, or terminal provider error.

- [ ] **Step 1: Write failing provider-ledger tests**

Add tests that set a complete `RSEBENCH_TOKEN_*` environment, then assert:

```python
first = client.complete(messages, cache_key="same")
second = client.complete(messages, cache_key="same")
summary = aggregate_token_usage(ledger_dir)
assert summary["attempted_calls"] == 2
assert summary["billed_tokens"]["total_tokens"] == 15
assert summary["logical_tokens"]["total_tokens"] == 30
assert summary["cache_hit_calls"] == 1
```

The fake first response supplies 10 prompt, 5 completion, and 15 total tokens.
Add a fake provider exception test asserting one `status=error`,
`usage_observed=false` event and no secret/error text in its JSONL shard.

- [ ] **Step 2: Run provider tests and verify RED**

Run:

```bash
pytest -q tests/providers/test_deepseek.py
```

Expected: new assertions fail because no events are emitted.

- [ ] **Step 3: Emit cache, provider, and terminal-error events**

In `DeepSeekClient.complete`:

```python
if cached is not None:
    record_token_event(
        usage=cached.usage,
        cache_hit=True,
        billed=False,
        status="success",
        source="rsebench.deepseek",
        provider="deepseek",
        model=cached.model,
        stage=role,
        request_key=key,
    )
    return cached
```

After a provider response is normalized, emit the corresponding billed success
before returning. In the provider exception handler, emit an unobservable error
using only `type(exc).__name__` before raising the existing redacted exception.
Do not emit a provider attempt for missing local credentials because no request
was issued.

- [ ] **Step 4: Verify GREEN and commit provider instrumentation**

Run:

```bash
pytest -q tests/providers/test_deepseek.py tests/providers/test_deepseek_capabilities.py
git diff --check
git add src/rsebench/providers/deepseek.py tests/providers/test_deepseek.py
git commit -m "feat: record DeepSeek token usage events"
```

Expected: provider tests pass and cache hits affect logical but not billed totals.

---

### Task 3: Instrument SkillOpt training and eval-only processes

**Files:**
- Modify external: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt/skillopt/model/openai_compatible_backend.py`
- Modify external: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt/scripts/eval_only.py`
- Modify external test: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt/tests/test_openai_compatible_backend.py`
- Create external test: `/home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt/tests/test_eval_only_token_summary.py`
- Refresh: `patches/baselines/skillopt-deepseek-thinking.patch`

**Interfaces:**
- Consumes: `record_token_event` through the RSEBench source path propagated by the harness.
- Produces: SkillOpt per-call ledger events and `eval_summary.json.token_summary`.

- [ ] **Step 1: Write failing SkillOpt backend event tests**

In the external repository, configure a temporary ledger through environment
variables, use `_CompletionRecorder`, call target and optimizer paths, and assert
the two events preserve their stages, models, and exact 2/3/5 usage. Add a client
that raises and assert the exhausted attempt emits an unobservable error event.

- [ ] **Step 2: Write a failing eval-only summary test**

Load `scripts/eval_only.py` as a module, patch its adapter and token tracker, run
the smallest fake evaluation, and assert:

```python
assert summary["token_summary"]["_total"] == {
    "calls": 1,
    "prompt_tokens": 2,
    "completion_tokens": 3,
    "total_tokens": 5,
}
```

- [ ] **Step 3: Run external tests and verify RED**

Run from the external SkillOpt root:

```bash
PYTHONPATH=/home/nvidia/yutao/lzt/self-evolution-robustness/.worktrees/rsebench-pilot/src \
  .venv/bin/pytest -q \
  tests/test_openai_compatible_backend.py \
  tests/test_eval_only_token_summary.py
```

Expected: ledger assertions and `token_summary` persistence fail.

- [ ] **Step 4: Record SkillOpt success/error events**

Add a guarded helper in `openai_compatible_backend.py`:

```python
def _record_rsebench_usage(**kwargs: Any) -> None:
    if not os.environ.get("RSEBENCH_TOKEN_LEDGER_DIR", "").strip():
        return
    from rsebench.usage import record_token_event
    record_token_event(source="skillopt.openai_compatible", **kwargs)
```

Call it after provider usage is normalized, with `stage=stage`,
`model=kwargs["model"]`, `cache_hit=False`, and `billed=True`. After all manual
retries fail, write one terminal unobservable error event. The event represents
the observable SkillOpt client operation; it does not invent usage for SDK
internals.

- [ ] **Step 5: Persist eval-only token summary**

Import `get_token_summary` and `reset_token_tracker`, reset immediately before
rollout, and add:

```python
summary = {
    "skill": skill_path,
    "split": split,
    "n_items": len(results),
    "hard": hard,
    "soft": soft,
    "token_summary": get_token_summary(),
}
```

- [ ] **Step 6: Verify external GREEN, refresh patch, and commit**

Run the focused suite, regenerate the existing patch using the repository's
tracked diff plus untracked adapted files, and verify reverse application:

```bash
PYTHONPATH=/home/nvidia/yutao/lzt/self-evolution-robustness/.worktrees/rsebench-pilot/src \
  .venv/bin/pytest -q \
  tests/test_openai_compatible_backend.py \
  tests/test_eval_only_token_summary.py \
  tests/test_officeqa_failures.py \
  tests/test_dapo_env.py
git -C /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt \
  apply --reverse --check \
  /home/nvidia/yutao/lzt/self-evolution-robustness/.worktrees/rsebench-pilot/patches/baselines/skillopt-deepseek-thinking.patch
git add patches/baselines/skillopt-deepseek-thinking.patch
git commit -m "feat: account for SkillOpt evaluation tokens"
```

Expected: focused external tests and reverse-patch check pass.

---

### Task 4: Propagate experiment context and aggregate each run

**Files:**
- Modify: `src/rsebench/evolution/skillopt_executor.py`
- Modify: `src/rsebench/evolution/runner.py`
- Modify: `src/rsebench/evolution/report.py`
- Modify: `src/rsebench/generation.py`
- Modify: `scripts/calibrate_officeqa.py`
- Modify: `tests/evolution/test_skillopt_executor.py`
- Modify: `tests/evolution/test_runner.py`
- Modify: `tests/evolution/test_noise_generation.py`
- Modify: `tests/evolution/test_calibration.py`

**Interfaces:**
- Consumes: context and artifact functions from Task 1.
- Produces: correctly separated generation/calibration/seed/clean/noisy/evaluation events and per-run summary/report.

- [ ] **Step 1: Write failing subprocess-context tests**

Capture the `env` passed to `SkillOptExecutor.command_runner` and assert:

```python
assert train_env["RSEBENCH_TOKEN_ARM"] == "clean"
assert train_env["RSEBENCH_TOKEN_STAGE"] == "evolution"
assert eval_env["RSEBENCH_TOKEN_ARM"] == "clean"
assert eval_env["RSEBENCH_TOKEN_STAGE"] == "eval"
assert Path(train_env["RSEBENCH_TOKEN_LEDGER_DIR"]).name == "token_usage"
```

Exercise output directories shaped like the real paired runner, not unrelated
temporary `arm` and `eval` siblings.

- [ ] **Step 2: Write failing paired aggregation tests**

Extend the fake executor to write seed/clean/noisy events to the configured run
ledger. Assert `result.token_usage`, `token_usage/summary.json`, and
`token_usage/report.md` exist and that a reused identical skill emits no extra
evaluation call.

- [ ] **Step 3: Verify orchestration RED**

Run:

```bash
pytest -q \
  tests/evolution/test_skillopt_executor.py \
  tests/evolution/test_runner.py \
  tests/evolution/test_noise_generation.py \
  tests/evolution/test_calibration.py
```

Expected: context and token artifact assertions fail.

- [ ] **Step 4: Add isolated subprocess environments**

Change `_run` to accept `token_environment: dict[str, str]` and merge it into a
fresh copy of `self.environment`. In `evolve`, derive run directory from
`output_dir.parent`, use `arm.arm`, benchmark/domain from the split, and stage
`evolution`. In `evaluate`, derive run directory from `output_dir.parents[1]`,
use the supplied stage as the arm for `seed|clean|noisy`, and always use ledger
stage `eval`; calibration runtimes use arm `calibration` and keep the runtime
name in a separate optional context label only if the schema supports it.

- [ ] **Step 5: Aggregate paired, generation, and calibration runs**

Add `token_usage: dict[str, Any]` to `PairedEvolutionResult`. Aggregate after the
last non-reused evaluation and before writing `result.json`; include billed,
logical, coverage, and unobservable calls in the paired Markdown report.

For `generate_from_profile` and `generate_evolution_pairs_from_profile`, create
the run directory before the model client and set generation context around all
model calls. Aggregate in `finally` so partial generation retains a report.

For OfficeQA calibration, set one ledger directory for the run, pass arm
`calibration` and runtime-specific stage to each evaluation subprocess, then
aggregate before writing its result/report.

- [ ] **Step 6: Verify orchestration GREEN and commit**

Run:

```bash
pytest -q \
  tests/evolution/test_skillopt_executor.py \
  tests/evolution/test_runner.py \
  tests/evolution/test_noise_generation.py \
  tests/evolution/test_calibration.py
git diff --check
git add src/rsebench/evolution src/rsebench/generation.py \
  scripts/calibrate_officeqa.py tests/evolution
git commit -m "feat: aggregate token usage for experiment runs"
```

Expected: each tested run has a validated summary and separated arm/stage groups.

---

### Task 5: Exact historical audit without estimates

**Files:**
- Create: `src/rsebench/usage/backfill.py`
- Create: `scripts/audit_token_usage.py`
- Create: `tests/usage/test_backfill.py`

**Interfaces:**
- Produces: `audit_historical_usage(project_root, output_dir) -> dict[str, Any]` and CLI flags `--project-root`, `--output-dir`.
- Consumes: old SkillOpt result/summary files, shared DeepSeek cache objects, and old evaluation conversations.

- [ ] **Step 1: Write failing fixture-based backfill tests**

Build a synthetic old project containing:

- one paired `result.json` with clean/noisy `_total` summaries;
- child stage summaries that must not be added again;
- two unique DeepSeek cache JSON files;
- three evaluation conversations without usage;
- one `reused.json` evaluation that must not count as an attempted call.

Assert exact billed tokens, unknown-context legacy cache grouping, three
unobservable calls, source file counts, and absence of an `estimated_tokens`
field.

- [ ] **Step 2: Run backfill tests and verify RED**

Run:

```bash
pytest -q tests/usage/test_backfill.py
```

Expected: import fails because the backfill module does not exist.

- [ ] **Step 3: Implement exact legacy scanners**

Implement three independent scanners:

```python
scan_skillopt_training_totals(project_root)
scan_deepseek_cache(project_root)
scan_unobservable_evaluations(project_root)
```

SkillOpt uses only each arm's `_total`. DeepSeek cache files are deduplicated by
resolved path and response hash, billed once, and assigned unknown experiment
context. Evaluation counting reads conversation files only under native eval
directories whose `eval_summary.json` lacks `token_summary`; reused evaluations
are skipped.

- [ ] **Step 4: Add the audit CLI and atomic reports**

The CLI writes `legacy-token-audit/summary.json` and `report.md`, prints the
summary path, and exits nonzero on malformed observable usage. It must describe
the result as an exact lower bound and print observed/unobservable call counts,
never a token estimate.

- [ ] **Step 5: Verify GREEN and commit historical audit**

Run:

```bash
pytest -q tests/usage/test_backfill.py
python scripts/audit_token_usage.py --help
git diff --check
git add src/rsebench/usage/backfill.py scripts/audit_token_usage.py \
  tests/usage/test_backfill.py
git commit -m "feat: audit observable historical token usage"
```

Expected: fixture audit passes and the CLI exposes only exact accounting fields.

---

### Task 6: Verification, live cache smoke, and next experiment plan

**Files:**
- Create: `docs/reports/token-accounting-status.md`
- Create: `docs/plans/next-validation-experiments.md`
- Modify: `docs/reports/current-experiment-status.md`

**Interfaces:**
- Consumes: all prior tasks and current experiment results.
- Produces: verified accounting status and an execution-ready validation plan for spreadsheet, math, and document noise.

- [ ] **Step 1: Run all offline verification**

Run:

```bash
pytest -q
PYTHONPATH=/home/nvidia/yutao/lzt/self-evolution-robustness/.worktrees/rsebench-pilot/src \
  /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt/.venv/bin/pytest -q \
  /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt/tests/test_openai_compatible_backend.py \
  /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt/tests/test_eval_only_token_summary.py \
  /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt/tests/test_officeqa_failures.py \
  /home/nvidia/yutao/lzt/self-evolution-robustness/methods/external/skillopt/tests/test_dapo_env.py
```

Expected: all main and focused external tests pass.

- [ ] **Step 2: Run one real billed request and one identical cache hit**

Use the existing locked provider configuration with thinking disabled and a
fresh smoke run directory. Issue a 64-token maximum request that returns exactly
`OK`, then issue the identical request through the same cache key. Assert from
the generated summary:

```python
assert summary["attempted_calls"] == 2
assert summary["successful_calls"] == 2
assert summary["observed_coverage"] == 1.0
assert summary["cache_hit_calls"] == 1
assert summary["billed_tokens"]["total_tokens"] > 0
assert summary["logical_tokens"]["total_tokens"] == (
    2 * summary["billed_tokens"]["total_tokens"]
)
```

- [ ] **Step 3: Audit current historical artifacts**

Run the new CLI against
`/home/nvidia/yutao/lzt/self-evolution-robustness`, write the report beneath the
shared outputs root, and verify its exact lower bound against direct sums of
legacy SkillOpt `_total` and unique DeepSeek cache usage.

- [ ] **Step 4: Write the next validation experiment plan**

Create `docs/plans/next-validation-experiments.md` with:

- spreadsheet C1 replication on an additional baseline before expansion;
- math redesign around unlabeled provenance conflict and feedback corruption,
  with a 5/3/10 screening stage followed by 15/8/50 confirmation only after a
  skill-path divergence gate;
- OfficeQA evidence-conflict operators that preserve oracle documents but alter
  provenance attribution, screened on 6/3/10 and confirmed on 12/6/20;
- clean/noisy same-seed paired evolution, untouched clean test, identical model
  budget, minimum harmful gap `0.05`, paired confidence intervals, update-path
  diagnostics, and token budgets from the new billed ledger;
- stopping rules that retain null and opposite-direction results and prohibit
  full multi-method expansion until at least two domains and two baselines show
  reproducible harmful evolution gaps.

- [ ] **Step 5: Perform final integrity checks and commit**

Run:

```bash
git diff --check
if git grep -qE 'hf_[A-Za-z0-9]{20,}|(sk-|api[_-]?key[[:space:]]*[:=][[:space:]]*)[A-Za-z0-9_-]{20,}' -- ':!.env.example'; then exit 1; fi
git status --short
git add docs/reports/token-accounting-status.md \
  docs/reports/current-experiment-status.md \
  docs/plans/next-validation-experiments.md
git commit -m "docs: plan next robustness validation experiments"
```

Expected: no diff errors or tracked secrets; documentation cites exact ledger
artifacts and distinguishes measured lower bounds from unobservable history.
