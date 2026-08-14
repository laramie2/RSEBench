# Noise Validation Pilot Readiness

Date: 2026-08-12

## Outcome

The benchmark-construction pipeline and the first model-backed Pilot-A are
complete. The DAPO rule-noise operator was rejected because clean and noisy scores
were both 0.6 at L1/L2/L3, giving zero aggregate effect. No GPT-5.5 call or
fallback model was used; the completed online run used `deepseek-v4-flash`.

The current evidence establishes generator feasibility and label preservation; it
does **not** yet establish that every operator causes a statistically useful
performance drop or reverse self-evolution.

## Completed offline validation

| Domain/profile | Sample and operators | Result | Run directory |
|---|---|---|---|
| SpreadsheetBench | 10 tasks × failed-attempt + backup-sheet + semantic-decoy-sheet | 30/30 accepted | `outputs/runs/generation/20260812T055139721216Z-95707cbb23` |
| OfficeQA demo | 10 tasks × failed-attempt + semantic-decoy-document + gold-rank displacement | 29 accepted, 1 not applicable; applicability 90% | `outputs/runs/generation/20260812T055139665008Z-5daf331d5d` |
| OfficeQA formal | 10 tasks × failed-attempt + semantic-decoy-document + gold-rank displacement | 30/30 accepted, including multi-source questions | `outputs/runs/generation/20260812T072847372126Z-a36f58c624` |
| DocVQA | 10 tasks × two C1 operators; margin-clutter audited separately | 20 C1 accepted; 10 image cases not applicable because answer boxes are absent | `outputs/runs/generation/20260812T055139760062Z-79dab34010` |
| DAPO, rule | 5 tasks × failed-attempt | 5/5 accepted structurally; execution effect later rejected | `outputs/runs/generation/20260812T055139703890Z-1794c3b80d` |
| DAPO, model | 5 tasks × flawed-partial-solution | 0/5 accepted; hard gates rejected leakage, invalid JSON, or critic disagreement | `outputs/runs/generation/20260812T080953382224Z-723dcd31a0` |

Spreadsheet validation checks every original sheet’s formulas, values, number
formats, merged ranges, and visibility while tolerating only XLSX round-trip empty
cell and sub-precision float representation changes. The official two-decimal
answer-range semantics remain stricter at evaluation time where relevant.

OfficeQA fixtures guarantee that every referenced gold document appears exactly
once at consecutive positions beginning at the requested rank. They exclude gold
and duplicate documents from decoys, screen contextual answer leakage, and hash
the entire rank order. The formal selector builds one lexical feature index for
the selected questions and reuses it across tasks rather than rescanning the
383 MB corpus per question. The older demo smoke retained one not-applicable case
because it lacked enough safe unique decoys; the formal 10-task smoke accepted all
30 generated variants.

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

Completed run state:

```text
status=experiment_complete
model=deepseek-v4-flash
run=outputs/runs/pilot-a/20260812T082228672656Z-dapo-failed-attempt
```

Result: clean/L1/L2/L3 were all 0.6, `effect_l2=0`, and the
`minimum_effect` gate failed. One task degraded and one improved, so the aggregate
effect cancelled. This operator must be redesigned before benchmark inclusion.

To reproduce with the configured key in `.env`:

```bash
python -m rsebench.cli provider-check \
  --config configs/pilot/deepseek-v4-flash.yaml
python -m rsebench.cli math-pilot-a --limit 5
```

The provider is hard-locked to the official `https://api.deepseek.com` endpoint and
model ID `deepseek-v4-flash`; cached responses are reused and credentials are never
written to run manifests. Execution now uses explicit non-thinking mode with a
2048-token cap after a retained thinking-enabled run produced four empty responses
for one task at the 8192-token reasoning limit.

## Pilot-B status

Pilot-B full self-evolution is intentionally not launched yet. Preconditions are:

1. a Pilot-A operator demonstrates a real clean-to-noisy drop without collapsing
   all scores to zero;
2. the selected baseline reproduces its native clean pilot result;
3. the baseline's native DeepSeek/OpenAI-compatible route is verified;
4. the same frozen pilot manifest is used across methods.

Spreadsheet Pilot-B should start with SkillOpt and Trace2Skill, then add SkillGrad.
OfficeQA corpus access is now satisfied. Pilot-B should first reproduce SkillOpt
on the formal clean manifest and EvoSkill on its native demo, then run the reviewed
EvoSkill formal-data adapter. DAPO has no native two-method intersection, so method
adaptation must be declared rather than presented as native reproduction.

## Verification

At this checkpoint the full harness suite has 67 tests, all passing, with 88%
line coverage. It covers registries, download idempotence, contracts, provider
lock/cache, cross-domain C1 noise, spreadsheet preservation, OfficeQA retrieval
fixtures, DocVQA masks, math leakage and critics, group-isolated splits,
calibration gates, generation/experiment orchestration, and skill-native audits.
