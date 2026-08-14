# Token Accounting Status

Date: 2026-08-13

## Accounting contract

New RSEBench runs use an append-only, process-sharded token ledger. Every
observable model operation records model, provider, run, domain, benchmark,
arm, stage, cache status, and provider-reported prompt/completion/total tokens.
Prompts, responses, tool payloads, raw provider errors, and credentials are not
stored in the ledger.

Two views are reported:

- `billed_tokens` counts successful provider calls that were not served by the
  local cache. This is the default experiment-budget view.
- `logical_tokens` counts the model usage represented by all successful calls,
  including local cache hits. It measures computational workload independently
  of whether a request was billed again.

Failed provider requests are recorded as attempted but `unobservable` because
the API does not return usage. Historical missing usage is never reconstructed
from text length.

Each new run writes:

```text
token_usage/
├── events/<pid>.jsonl
├── summary.json
└── report.md
```

The integration covers the shared DeepSeek client, SkillOpt target/optimizer
calls, eval-only summaries, noise generation, paired self-evolution,
OfficeQA calibration, and expanded artifact evaluation. Cache hits affect only
the logical view. Identical event IDs are deduplicated; conflicting duplicates
and malformed usage fail aggregation.

## Live provider verification

A fresh `deepseek-v4-flash` request was issued with
`https://api.deepseek.com`, thinking disabled, and a 64-token completion cap.
An identical second call was served from the isolated local cache.

| Metric | Result |
|---|---:|
| Attempted / successful calls | 2 / 2 |
| Cache hits | 1 |
| Observed coverage | 1.0000 |
| Billed prompt / completion / total | 9 / 2 / 11 |
| Logical prompt / completion / total | 18 / 4 / 22 |

Artifact:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/token-ledger-smoke/20260813T035052824278Z/token_usage/summary.json`

The model returned `OK.` rather than the requested literal `OK`; this affected
only a response-format assertion, not the usage or cache checks. No second
provider request was issued to correct punctuation.

## Historical exact lower bound

The legacy audit reads only persisted SkillOpt clean/noisy training `_total`
records and unique DeepSeek response-cache objects. Child stage totals are not
added to `_total`, and reused evaluations are skipped. Old evaluation
conversations without a persisted usage object are counted as unobservable and
contribute zero tokens.

| Source | Observable calls | Prompt | Completion | Total |
|---|---:|---:|---:|---:|
| SkillOpt clean/noisy training `_total` | 2,391 | 22,202,082 | 1,509,142 | 23,711,224 |
| Unique DeepSeek response cache | 891 | 387,180 | 572,106 | 959,286 |
| **Exact billed lower bound** | **3,282** | **22,589,262** | **2,081,248** | **24,670,510** |

There are 588 legacy evaluation conversations with no stored usage. Relative to
the observable calls plus this conversation-level lower bound, observed call
coverage is `0.8481`. The audit does not claim that one conversation equals the
true number of provider turns; therefore both call count and token count remain
lower bounds for project history.

Audit artifact:
`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/legacy-token-audit/20260813-unified-ledger/summary.json`

The independent direct sums of the 47 SkillOpt summaries and 891 unique cache
files match the audit exactly.

## Verification evidence

- Main project: `210 passed`.
- Focused external SkillOpt adapter/environment suite: `13 passed`.
- The SkillOpt adaptation remains represented by the tracked reverse-applicable
  patch.
- New artifacts distinguish measured billed usage, cache-inclusive logical
  usage, and unavailable historical usage; no token estimates or currency-cost
  claims are emitted.
