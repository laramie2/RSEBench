# Runtime-noise FAQ documentation design

## Goal

Add a stable Chinese FAQ that explains N3/N4 to project collaborators and external method authors without mixing conceptual guidance into the executable noise-stage contract.

## Documentation shape

Create `docs/qa/runtime-noise-faq.md` with six sections:

1. basic distinction between N1/N2 and N3/N4;
2. why N3/N4 are part of RSEBench as an evaluation suite but not static dataset artifacts;
3. the robustness hypotheses behind trajectory omission and feedback misattribution;
4. how method adapters and benchmark policies support new baselines and datasets;
5. how a future self-evolution pipeline exposes identity-preserving runtime hooks;
6. how external self-evolution methods run and report RSEBench evaluations, including unsupported-stage handling.

The FAQ must explicitly state that N3 and N4 are independent experiment arms, that protected execution outcomes remain immutable, and that a method without a faithful feedback boundary cannot report an N4 null effect.

## Navigation changes

Add links to the FAQ from:

- `docs/README.md`, under the new-collaborator entry points;
- `docs/project-onboarding.md`, after the concise N1–N4 definition;
- `docs/protocols/noise-stage-interface.md`, as the conceptual companion to the normative interface.

Existing protocol language remains authoritative. The FAQ explains the protocol but does not redefine operator IDs, release identities, protected fields, or the validation matrix.

## Verification

- scan the FAQ for placeholders and contradictions;
- verify all added relative Markdown links resolve;
- run the repository documentation-link test or the nearest existing targeted test;
- confirm the diff changes only the new FAQ and its three navigation entry points.
