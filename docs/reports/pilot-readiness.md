# Noise Validation Pilot Readiness

Date: 2026-08-12

## Outcome

The benchmark-construction pipeline is ready for model-backed Pilot-A, but the
effectiveness experiment is not complete because `DEEPSEEK_API_KEY` is empty. No
GPT-5.5 call or fallback model was used.

The current evidence establishes generator feasibility and label preservation; it
does **not** yet establish that every operator causes a statistically useful
performance drop or reverse self-evolution.

## Completed offline validation

| Domain/profile | Sample and operators | Result | Run directory |
|---|---|---|---|
| SpreadsheetBench | 10 tasks × failed-attempt + backup-sheet + semantic-decoy-sheet | 30/30 accepted | `outputs/runs/generation/20260812T055139721216Z-95707cbb23` |
| OfficeQA demo | 10 tasks × failed-attempt + semantic-decoy-document + gold-rank displacement | 29 accepted, 1 not applicable; applicability 90% | `outputs/runs/generation/20260812T055139665008Z-5daf331d5d` |
| DocVQA | 10 tasks × two C1 operators; margin-clutter audited separately | 20 C1 accepted; 10 image cases not applicable because answer boxes are absent | `outputs/runs/generation/20260812T055139760062Z-79dab34010` |
| DAPO | 5 tasks × rule failed-attempt; model flawed-solution queued | 5 accepted; 5 model-backed candidates blocked by offline mode | `outputs/runs/generation/20260812T055139703890Z-1794c3b80d` |
| OfficeQA formal | access check | blocked on gated dataset/corpus | `outputs/runs/generation/20260812T055139675622Z-a36f58c624` |

Spreadsheet validation checks every original sheet’s formulas, values, number
formats, merged ranges, and visibility while tolerating only XLSX round-trip empty
cell and sub-precision float representation changes. The official two-decimal
answer-range semantics remain stricter at evaluation time where relevant.

OfficeQA fixtures guarantee exactly one gold document at the requested rank,
exclude exact/duplicate documents, screen contextual answer leakage, and hash the
entire rank order. One L2 task lacked four safe unique decoys and was correctly
marked not applicable rather than forced.

DocVQA’s released Parquet subset has images and answers but no OCR answer boxes.
The pipeline therefore refuses image clutter instead of risking label corruption.
Prompt noise is available for all 534 fixed IDs. DeepSeek V4 Flash is text-only, so
DocVQA visual execution needs a separately approved vision model in a later phase;
it cannot be evaluated by silently proxying through GPT-5.5.

## DeepSeek Pilot-A entry point

The paired DAPO experiment is implemented. It runs the same five fixed tasks under
clean, L1, L2, and L3 failed-attempt prompts, parses the final answer, stores token
usage and cache status, and applies structural, invariance, leakage, minimum-effect,
severity-monotonicity, and floor-avoidance gates.

Current run state:

```text
status=blocked_on_credentials
model=deepseek-v4-flash
run=outputs/runs/pilot-a/20260812T055220737612Z-dapo-failed-attempt
```

After placing a valid key in `.env`:

```bash
python -m rsebench.cli provider-check \
  --config configs/pilot/deepseek-v4-flash.yaml
python -m rsebench.cli math-pilot-a --limit 5
```

The provider is hard-locked to the official `https://api.deepseek.com` endpoint and
model ID `deepseek-v4-flash`; cached responses are reused and credentials are never
written to run manifests.

## Pilot-B status

Pilot-B is intentionally not launched yet. Preconditions are:

1. a Pilot-A operator demonstrates a real clean-to-noisy drop without collapsing
   all scores to zero;
2. the selected baseline reproduces its native clean pilot result;
3. a reviewed DeepSeek adapter is added to the baseline launcher;
4. the same frozen pilot manifest is used across methods.

Spreadsheet Pilot-B should start with SkillOpt and Trace2Skill, then add SkillGrad.
OfficeQA should start with EvoSkill’s demo and SkillOpt only after formal corpus
access. DAPO has no native two-method intersection, so method adaptation must be
declared rather than presented as native reproduction.

## Verification

At this checkpoint the full offline suite has 54 tests, all passing, with 84%
line coverage. It covers registries, download idempotence, contracts, provider
lock/cache, cross-domain C1 noise, spreadsheet preservation, OfficeQA retrieval
fixtures, DocVQA masks, math leakage and critics, group-isolated splits,
calibration gates, generation/experiment orchestration, and skill-native audits.
