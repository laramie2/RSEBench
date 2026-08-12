# Current API Adaptation and Paired-Evolution Status

Date: 2026-08-12

## Executive conclusion

The shared harness now runs paired clean/noisy self-evolution from the same seed
skill, with identical task order, method seed, budget, and an untouched clean test
split. All online calls in this phase used exactly `deepseek-v4-flash` at
`https://api.deepseek.com` with thinking explicitly disabled. No GPT model was
used.

Seven baseline repositories now pass real DeepSeek transport, structured-output,
and tool-use smokes. This proves the API adaptation layer, not full native
self-evolution support for every method. SkillOpt is currently the only baseline
connected end to end to the shared paired-evolution harness across the three main
pilot domains.

The main efficacy result is mixed:

- Spreadsheet prompt noise produced the intended degradation and reverse
  evolution in one bounded pilot: clean-evolved `0.500`, noisy-evolved `0.375`,
  gap `+0.125` on eight untouched clean test tasks. The paired bootstrap interval
  is `[0.000, 0.375]`, so this is feasibility evidence, not a final statistical
  claim.
- DAPO math noise changed the evolution path: the clean arm accepted a new skill
  after validation improved from `0.667` to `1.000`, while the noisy arm retained
  the seed. Both nevertheless scored `0.600` on ten clean test tasks, with two
  opposite task flips canceling in aggregate.
- OfficeQA prompt/rank pilots did not establish an effect. SearchQA prompt noise
  and stronger evidence-level semantic decoys also produced zero gap because the
  selected clean test tasks were at a `1.000` ceiling and both arms rejected all
  candidate skills.
- DocVQA visual execution is blocked by provider capability: this DeepSeek
  endpoint rejects `image_url` input. The interrupted run is invalid and its
  zeros must never be reported as benchmark scores.

Therefore the construction and execution infrastructure is ready, but only the
spreadsheet lane has passed the current minimum-effect feasibility criterion.
The math lane has mechanism evidence without aggregate degradation; the document
lane still needs a non-floor/non-ceiling native task setting before any full-data
study.

## Experimental protocol now enforced

For every paired run:

1. Clean and noisy arms use the same seed skill, task IDs/order, method seed, and
   optimization budget.
2. Noise is applied only to evolution train and validation records. The test
   records are clean and hash-audited.
3. Noise candidates must pass structural validity, label invariance, solvability,
   and answer-leak gates before materialization.
4. Hard-gate backfill scans candidates in frozen manifest order and never reads a
   clean-test score. Rejected candidates remain in the generation audit.
5. Seed, clean-evolved, and noisy-evolved skills are evaluated on the same clean
   test tasks. Identical skill hashes reuse the same evaluation so stochastic
   duplicate calls cannot create a false gap.
6. Reports separate final score, evolution gain, evolution gap, paired bootstrap
   interval, and reverse-evolution status.

The current cross-domain taxonomy exercised in execution is:

- `C1/M2`: failed-attempt or flawed-solution noise in task communication.
- `C2/M1`: additive evidence/artifact noise, including SearchQA semantic decoy
  passages and spreadsheet artifact distractors.
- `C3/M5`: retrieval order/access noise, represented by OfficeQA gold-rank
  displacement.

## Paired self-evolution results

| Domain / operator | Train / val / clean test | Seed | Clean evolved | Noisy evolved | Gap | Interpretation |
|---|---:|---:|---:|---:|---:|---|
| SpreadsheetBench-Verified, C1 failed attempt | 5 / 5 / 8 | 0.500 | 0.500 | 0.375 | +0.125 | Reverse evolution; noisy candidate passed noisy validation and harmed one clean-test task |
| OfficeQA, C1 failed attempt | 10 / 2 / 8 | 0.500 | 0.500 | 0.500 | 0.000 | Both arms retained seed; no effect |
| OfficeQA, C3 rank displacement smoke | 3 / 1 / 2 | 1.000 | 1.000 | 1.000 | 0.000 | Harness smoke only; train rollouts at floor |
| DAPO, C1 flawed partial solution | 5 / 3 / 10 | 0.600 | 0.600 | 0.600 | 0.000 | Evolution paths diverged, aggregate test effect canceled |
| SearchQA, C1 failed attempt | 6 / 2 / 8 | 1.000 | 1.000 | 1.000 | 0.000 | Test ceiling; all candidate skills rejected |
| SearchQA, C2 semantic decoy evidence | 6 / 2 / 8 | 1.000 | 1.000 | 1.000 | 0.000 | Gold evidence remained visible; noise still did not affect evolution |
| SearchQA, C2 decoy + label-free context-length stratum | 6 / 2 / 8 | 1.000 | 1.000 | 1.000 | 0.000 | Same ceiling after a pre-evaluation difficulty proxy |

### Reproducible run locations

- Spreadsheet paired result:
  `/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T105048200231Z-skillopt`
- OfficeQA prompt result:
  `/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T105816665296Z-skillopt`
- OfficeQA rank smoke:
  `/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T112341133412Z-skillopt`
- DAPO challenge result:
  `/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T113615435943Z-skillopt`
- SearchQA prompt result:
  `/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T115904945216Z-skillopt`
- SearchQA evidence result:
  `/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T120621460859Z-skillopt`
- SearchQA label-free context-length result:
  `/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/paired-evolution/20260812T121001957307Z-skillopt`

The valid SearchQA evidence manifest is:

`/home/nvidia/yutao/lzt/self-evolution-robustness/outputs/runs/evolution-noise/20260812T120505962841Z-c5e57a4286/pair_manifest.json`

Its six train and two validation candidates all passed the gates. The earlier C1
prompt manifest used automatic hard-gate backfill: 17 candidates were attempted,
9 answer-leaking candidates were rejected, and 8 valid pairs were retained.

## Dataset and domain readiness

| Dataset | Local state | Shared-harness state | Efficacy state |
|---|---|---|---|
| SpreadsheetBench-Verified | Materialized and frozen | Native SkillOpt train/eval passed | Positive bounded feasibility result |
| OfficeQA | Gated data and corpus downloaded | Prompt and retrieval-rank paths execute | Negative/floor pilots; redesign task calibration |
| DAPO fixed 1000 | Materialized with frozen 400/100/500 partition | Native numeric evaluator and SkillOpt environment passed | Path divergence, zero aggregate gap |
| LiveMathematicianBench | Downloaded, profiled, and split | Bridge/config available | Not used for the current aggregate pilot after DAPO proved more directly executable |
| DocVQA 10% | 534 rows and 534 images materialized | JSON/image bridge passes local tests | Online visual execution blocked by text-only endpoint |
| SearchQA SkillOpt split | 400/200/1400 official-ID payload materialized | Native train/eval and C1/C2 pipelines passed | Repeated ceiling; retain as negative result |
| Skill-native datasets | Existing distribution/format audit retained | No shared evolution run in this phase | Mechanism/diagnostic lane only |

SearchQA's RSE split is recreated by
`scripts/materialize_searchqa_split_manifest.py`; it preserves the released
SkillOpt train/validation/test IDs and defines disjoint 20-task pilot-evolve and
10-task pilot-eval lists. DocVQA image bytes are recreated by
`scripts/materialize_docvqa_images.py`.

## Baseline deployment matrix

All seven rows below passed real online transport, JSON structured output, and a
tool-use smoke with `deepseek-v4-flash` and thinking disabled.

| Baseline | API/tool smoke | Adapted roles | Native benchmark run | Shared paired self-evolution |
|---|---|---|---|---|
| Trace2Skill | Passed | executor, analysis, optimizer | Spreadsheet clean skill-preloaded smoke passed previously | Not yet connected |
| SkillOpt | Passed | target, optimizer | Spreadsheet, OfficeQA, DAPO, SearchQA passed; DocVQA blocked online | Passed end to end in three main domains |
| SkillGrad | Passed | executor, diagnoser, momentum, patcher | Not rerun on shared manifest | Not yet connected |
| EvoSkill | Passed | executor, proposer, evaluator | No shared-domain native run in this phase | Not yet connected |
| Skills-Coach | Passed | generator, optimizer, executor, judge | Skill-native task run pending | Not yet connected |
| SkillFlow | Passed | worker, patcher | Tool worker passed; benchmark container run pending | Not yet connected |
| FederatedSkill | Passed | worker, patcher, merger | Worker and merger tool paths passed | Not yet connected |

The latest FederatedSkill smoke is at:

`/home/nvidia/yutao/lzt/self-evolution-robustness/.worktrees/rsebench-pilot/outputs/runs/baseline-smoke/20260812T121242422535Z-federatedskill`

The other passing smoke directories are recorded under the same
`outputs/runs/baseline-smoke` directory. Reproducible source patches are stored in
`patches/baselines/`; each patch matches the corresponding dirty external method
checkout (Trace2Skill requires whitespace-tolerant application because the
upstream file uses mixed CRLF/LF endings).

## Verification evidence

- Main RSEBench harness: `157 passed`.
- SkillOpt full repository suite: `906 passed, 6 skipped, 130 subtests passed`.
- Focused API-adaptation suites: Trace2Skill `2 passed`, SkillGrad `2 passed`,
  EvoSkill `1 passed`, Skills-Coach `4 passed`, SkillFlow `1 passed`, and
  FederatedSkill `2 passed`.
- All seven online baseline smoke ladders passed through `tool`.
- All SkillOpt paired reports include per-task scores and paired bootstrap
  intervals. No provider error result is counted as an experimental score.

## Next experiment gate

Do not start a full multi-method benchmark run yet. The next bounded work should
be:

1. Reproduce the spreadsheet effect with at least one additional baseline and a
   larger untouched clean-test sample.
2. For math, expand clean-test evaluation of the already divergent clean/noisy
   skills before changing the operator; the current ten-task aggregate is too
   small and exactly cancels.
3. Replace SearchQA as the primary document efficacy lane, or calibrate an
   OfficeQA subset where the seed score is neither floor nor ceiling before
   generating new noise. Keep SearchQA as a negative/control lane.
4. Only after each domain has a non-floor/non-ceiling clean seed and at least one
   operator with a reproducible positive evolution gap should the full shared
   harness be applied to every baseline.
