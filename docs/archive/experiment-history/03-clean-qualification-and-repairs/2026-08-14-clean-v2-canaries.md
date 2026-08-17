# Clean v2 Failure-Targeted Canary Report

Date: 2026-08-14

All four failure-targeted clean-v2 canaries passed their engineering gates.
This establishes that every selected baseline can execute its clean
self-evolution loop, produce a changed artifact, accept at least one update,
finish the clean test, and satisfy its runtime/coverage requirements. These
single-seed canaries are diagnostic evidence only; they do not by themselves
establish three-seed efficacy readiness and cannot unlock N1-N4.

| Cell | Seed to evolved clean score | Accepted updates | Run time | Seed / evolution / final-test time | Calls | Billed tokens |
|---|---:|---:|---:|---:|---:|---:|
| SpreadsheetBench-Verified / SkillOpt | `0.3333 -> 0.4333` (`+0.1000`) | 1 | 665.4 s | 139.1 / 399.6 / 126.7 s | 141 | 359,181 |
| OfficeQA Full / SkillOpt | `0.6500 -> 0.6500` (`0.0000`) | 1 | 942.8 s | 155.4 / 632.6 / 154.8 s | 460 | 5,367,635 |
| WebShop / SkillAdaptor | `0.1025 -> 0.3000` (`+0.1975`) | 5 | 11,860.4 s | 652.2 / 10,651.1 / 557.1 s | 5,583 | 7,659,245 |
| SkillLearnBench offer-letter-generator / self-feedback | `0.3333 -> 1.0000` (`+0.6667`) | 2 | 887.5 s | 220.0 / 411.9 / 255.6 s | 114 | 786,346 |

The four selected passing results contain 6,298 observed calls and 14,172,407
billed tokens: 13,005,056 prompt and 1,167,351 completion tokens. Provider
failure count is zero and token observation coverage is 100%. Their summed
scheduler unit time is 14,361.4 seconds; WebShop is the dominant critical path
at about 3 hours 17 minutes 42 seconds.

The compact manifest records run- and stage-level times. Every source result
also contains the full run/stage/task three-level timing records requested for
later cost and latency analysis.

## OfficeQA repair evidence

OfficeQA required two bounded compatibility repairs before producing a valid
canary:

1. The original run accepted two updates and improved `0.55 -> 0.60`, but one
   seed task had malformed tool-call JSON and one evolved task exhausted the
   tool budget. It failed the runtime gate.
2. The first repaired run completed with no execution failures, but all three
   candidates were rejected, so the artifact did not change. This proved the
   execution path but did not pass the accepted-update canary gate.
3. A short confirmation run exposed two remaining output-distribution cases:
   malformed tool arguments aborted the whole task, and the final budget round
   still exposed tools. It was stopped after the seed result made failure
   decisive.
4. The final repair isolates malformed tool calls, supplies a valid tool-error
   observation, forces a bounded answer-only recovery, hides tools on the last
   round, and sends untagged answer-only output through the unchanged official
   direct-answer scorer. The final canary had empty seed/evolved execution
   failures, 100% parseability, one accepted update, and a validation gain from
   `0.5833` to `0.6667`.

The OfficeQA clean-test gain is still zero. The valid interpretation is that
SkillOpt now executes and updates correctly on OfficeQA, while stable efficacy
remains unproven. It is not evidence that OfficeQA clean evolution is reliably
beneficial.

## Full engineering cost

Including superseded and interrupted OfficeQA attempts, the complete canary
and repair process used 7,291 observed calls and 26,149,837 billed tokens:
24,500,693 prompt and 1,649,144 completion tokens. Provider failure count is
zero and observation coverage is 100%. The summed scheduler unit time across
all attempts is 16,340.2 seconds. Superseded attempt IDs, result hashes,
durations, and failure reasons remain visible in the diagnostic manifest; raw
outputs remain local and gitignored.

## Next gate

The next valid step is the fixed three-seed clean-v2 matrix. Each cell must
produce at least two engineering-valid seeds and at least two strictly positive
clean gains. Only if all four cells satisfy both levels may the immutable clean
release be frozen and N1-N4 begin. The OfficeQA canary's neutral final gain
makes that formal efficacy check especially important.

Machine-readable evidence is stored in
`releases/diagnostic/clean-v2-canaries/manifest.json`.
