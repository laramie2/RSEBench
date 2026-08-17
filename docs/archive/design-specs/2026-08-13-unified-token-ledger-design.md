# Unified Token Ledger Design

Date: 2026-08-13

## Objective

Add one auditable token-accounting contract to every RSEBench online model
path. New experiments must distinguish actual provider-billed work from logical
model work, survive subprocesses and interrupted runs, and expose incomplete
historical coverage without replacing missing usage with estimates.

The ledger covers noise generation, independent critics, calibration, seed
evaluation, clean/noisy self-evolution, clean-test evaluation, and API smoke
tests. It records token usage only; it does not estimate monetary cost because
the selected `deepseek-v4-flash` endpoint does not expose a stable price table in
the experiment artifacts.

## Selected architecture

Use an append-only, per-run event ledger. Every model client writes one event
immediately after a top-level request succeeds, fails, or returns from the local
cache. Each process writes to its own JSONL shard under
`token_usage/events/<process-id>.jsonl`, avoiding cross-process partial writes.
An idempotent aggregator reads all shards, removes duplicate event IDs, validates
the accounting invariants, and writes `token_usage/summary.json` plus
`token_usage/report.md`.

This approach is preferred over final-summary-only accounting because a final
summary disappears when a run is interrupted. It is preferred over an API proxy
because it does not introduce a new service into validation experiments.

## Event contract

Each JSONL event uses schema version `rsebench.token-usage.v1` and contains:

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | Exact ledger schema identifier |
| `event_id` | string | Stable SHA-256 identity used for deduplication |
| `timestamp` | UTC ISO-8601 string | Time the client operation completed |
| `run_id` | string | Experiment directory identifier |
| `domain` | string | `spreadsheet`, `math`, `document`, `skill_native`, or `unknown` |
| `benchmark` | string | Dataset identifier |
| `arm` | string | `generation`, `calibration`, `seed`, `clean`, `noisy`, `evaluation`, or `smoke` |
| `stage` | string | Model role such as `rollout`, `analyst`, `merge`, `ranking`, `noise_generator`, `critic`, or `eval` |
| `provider` | string | Provider identifier, currently `deepseek` |
| `model` | string | Exact model returned by the provider or configured model on failure |
| `prompt_tokens` | non-negative integer | Provider-reported prompt tokens |
| `completion_tokens` | non-negative integer | Provider-reported completion tokens |
| `total_tokens` | non-negative integer | Provider total, validated against components when all are supplied |
| `cache_hit` | boolean | Whether the response came from the immutable local response cache |
| `billed` | boolean | Whether this client operation issued a provider request that can contribute billed tokens |
| `usage_observed` | boolean | Whether the provider/cache supplied token usage |
| `status` | string | `success`, `error`, or `interrupted` |
| `source` | string | Calling integration, for example `rsebench.deepseek` or `skillopt.openai_compatible` |
| `request_key` | string or null | Non-secret request/cache identity when available |
| `error_type` | string or null | Exception class only; no raw exception text or credentials |

For a successful response, `total_tokens` must equal the provider total if the
provider supplies it; otherwise it equals prompt plus completion tokens. An
error or interrupted event with no response has zero token fields and
`usage_observed=false`. SDK-internal retry attempts cannot be reconstructed from
the OpenAI client response; the ledger records the observable top-level client
operation and marks a terminal failure unobservable rather than inventing retry
usage.

`event_id` hashes the run context, process ID, a process-local monotonic sequence,
request key, completion timestamp, cache status, and status. Aggregation accepts
the same event twice only when all fields are identical; a repeated event ID with
different content is a hard validation error.

## Context propagation

The paired runner and other entry points populate the following environment
variables before invoking a model-bearing component:

- `RSEBENCH_TOKEN_LEDGER_DIR`
- `RSEBENCH_TOKEN_RUN_ID`
- `RSEBENCH_TOKEN_DOMAIN`
- `RSEBENCH_TOKEN_BENCHMARK`
- `RSEBENCH_TOKEN_ARM`
- `RSEBENCH_TOKEN_STAGE`

Explicit arguments supplied by a caller override environment defaults. The
paired runner changes `arm` and `stage` for seed evaluation, clean evolution,
noisy evolution, and each non-reused clean-test evaluation. A reused evaluation
does not emit a model event because it performs no model work.

`SkillOptExecutor` passes a fresh environment dictionary to each subprocess, so
clean and noisy subprocesses cannot overwrite one another's context. The shared
RSEBench source directory remains on `PYTHONPATH`; the adapted SkillOpt backend
uses the same ledger writer only when `RSEBENCH_TOKEN_LEDGER_DIR` is present.
Standalone upstream SkillOpt behavior remains unchanged when the variable is
absent.

## Accounting semantics

The aggregator publishes both requested accounting views:

- `billed_tokens`: sum of observed usage for events with `billed=true` and
  `cache_hit=false`.
- `logical_tokens`: sum of observed usage for every successful event, including
  cache hits.

It also publishes:

- attempted, successful, failed, interrupted, cache-hit, observed, and
  unobservable call counts;
- `observed_coverage = observed_calls / attempted_calls`, with `1.0` for an empty
  ledger;
- prompt, completion, and total tokens for both billed and logical views;
- grouped totals by domain, benchmark, arm, stage, model, status, and source.

The aggregator reads only event records. It never adds SkillOpt `_total` to the
same run's stage totals, so the existing summary cannot be double counted.
Existing SkillOpt `token_summary` remains a compatibility diagnostic, while the
ledger becomes the canonical cross-component source for new runs.

## Integration points

### RSEBench DeepSeek client

`DeepSeekClient.complete` emits:

- a billed success event on a provider response;
- a non-billed logical success event on a cache hit using the cached usage;
- an unobservable error event if the top-level provider operation raises.

Writing a ledger event must never include prompts, responses, tool arguments,
API keys, or raw error messages.

### SkillOpt OpenAI-compatible backend

The adapted backend emits an event for every successful target or optimizer
request with its existing stage and provider usage. Terminal request failures
emit an unobservable error event. The existing in-memory tracker continues to
feed native SkillOpt summaries but is not the canonical cross-run ledger.

### SkillOpt evaluation

`eval_only.py` resets its process-local tracker before rollout, writes
`token_summary` into `eval_summary.json`, and relies on per-call ledger events
for canonical accounting. This closes the current gap in seed, clean-test, and
OfficeQA calibration evaluation.

### Orchestration and reporting

Noise generation, calibration, paired evolution, expanded artifact evaluation,
and baseline smoke entry points create or receive a ledger directory and set the
run context before model calls. On normal completion they run the aggregator.
On interruption the event shards remain valid and can be aggregated later by a
standalone CLI.

## Historical backfill

A standalone audit command supports exact, non-estimated backfill:

1. Read native SkillOpt `token_summary._total` from old training artifacts and
   create one aggregate legacy event per arm. Do not import its stage children
   as additional totals.
2. Read each unique shared DeepSeek cache object once and create a project-level
   legacy cache event. It represents the original billed response. Because old
   cache objects do not store run context or cache-hit history, their run,
   domain, benchmark, arm, and stage are `unknown`, and historical logical cache
   reuse remains unobservable.
3. Count old evaluation conversations that lack usage as unobservable calls,
   grouped by their recoverable run/domain/arm context.
4. Never estimate historical token values from text length or mean tokens per
   call.

The backfill summary reports its source files, coverage, and limitations. It is
kept separate from a new run's native event ledger, preventing legacy aggregate
events from being mixed with new per-call events.

## Failure behavior

- Ledger shards are append-only and UTF-8 JSONL. A process creates its shard
  directory before its first write.
- A malformed event, negative token count, inconsistent observed total, or
  conflicting duplicate event ID makes aggregation fail loudly.
- A missing ledger environment is a no-op for reusable provider code, not a
  model-call failure.
- A ledger write failure is fatal inside RSEBench experiments because silently
  losing cost evidence would invalidate the requested accounting guarantee.
- Aggregation writes to a temporary file and atomically replaces the final
  summary/report.
- Failed and interrupted experiments remain aggregatable and show coverage below
  one when response usage was not observable.

## Security and privacy

The ledger stores metadata and integer usage only. It excludes prompt text,
completion text, documents, tool payloads, headers, environment values, and raw
exception messages. The existing tracked-secret scan remains part of final
verification.

## Test strategy and acceptance criteria

Unit tests must first fail and then cover:

1. billed provider success;
2. non-billed cache-hit success with logical tokens;
3. unobservable terminal error;
4. per-process shard creation and append behavior;
5. aggregation, grouping, coverage, and atomic output;
6. identical duplicate suppression and conflicting duplicate rejection;
7. malformed and inconsistent token events;
8. paired runner context separation for seed, clean, noisy, and evaluation;
9. SkillOpt eval-only token summary persistence;
10. exact legacy SkillOpt/cache backfill and unobservable evaluation calls.

The feature is accepted when:

- all existing tests and new ledger tests pass;
- a local fake-provider integration run produces both event shards and the two
  summaries without network access;
- a one-item real `deepseek-v4-flash` smoke reports
  `observed_coverage=1.0`, has positive billed and logical totals, and records
  thinking as disabled through the existing provider configuration;
- a second identical cached request increases logical tokens but not billed
  tokens;
- clean/noisy paired summaries equal the sum of their non-duplicated events;
- no tracked file contains an API or Hugging Face token.

## Scope exclusions

This change does not rerun historical experiments, estimate missing historical
tokens, calculate currency cost, introduce an API proxy, or connect additional
self-evolution baselines. Those activities remain separate from the accounting
infrastructure.
