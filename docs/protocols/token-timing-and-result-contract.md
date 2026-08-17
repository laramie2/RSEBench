# Token、时间与结果记录合同

> 当前合同版本：2026-08-17 UTC
>
> 2026-08-13 的 provider smoke 和历史 token audit 保留在后半部分作为验证证据，不是新的调用授权。

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

## Timing contract

每个新实验必须同时记录三级 UTC 时间。失败、取消和 blocked attempt 也必须写终态，不能因为没有 score 而缺失 timing record。

```text
run:
  started_at
  completed_at
  duration_seconds
  status

cell/attempt:
  queued_at
  started_at
  completed_at
  duration_seconds
  status

provider call:
  started_at
  completed_at
  latency_seconds
  prompt_tokens
  completion_tokens
  total_tokens
  cached
```

- 时间戳使用带时区的 UTC ISO-8601；
- duration 使用单调时钟计算，不能用字符串时间相减；
- provider、baseline engine 和 RSEBench orchestration 时间分开聚合；
- parallel cell 的 wall time 不能用所有 cell duration 的简单求和替代；
- resume 必须保留原 attempt，并创建新的 attempt timing，不覆盖旧记录。

## Result contract

每个终态 attempt 至少记录：release/matrix identity、domain、benchmark、method、stage、operator、seed、status、failure class、input/output/audit locator、score、skill artifact identity、token summary 和 timing summary。

Paid provider call 的 token observation coverage 必须为 100%。API 未返回 usage 的失败调用记录为 `unobservable`，不得按文本长度估算。聚合必须分别报告 billed、logical、cached 和 unavailable usage。

结果文件使用原子写入和不可变 attempt directory。重复聚合只能创建派生 summary，不能回写原始 event、trajectory、feedback 或 provider record。

## Verification evidence

- Main project: `210 passed`.
- Focused external SkillOpt adapter/environment suite: `13 passed`.
- The SkillOpt adaptation remains represented by the tracked reverse-applicable
  patch.
- New artifacts distinguish measured billed usage, cache-inclusive logical
  usage, and unavailable historical usage; no token estimates or currency-cost
  claims are emitted.
