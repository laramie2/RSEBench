# Validated and candidate methods

Third-party source is never vendored. `validated/` contains immutable releases,
upstream/environment locks, integration metadata, and replayable patches;
`candidates/` contains methods that cannot enter the validation matrix yet.
Local clones belong in each method's ignored `source/` directory. During the
one-version transition, `methods/external/` remains a read-only fallback.

## Baseline patch order

Patches are applied from each external repository root. Core-1 calibration
patches are incremental and therefore follow the provider/evidence patches.

## SkillOpt

```bash
git apply "$RSEBENCH_ROOT/methods/validated/skillopt/patches/skillopt-deepseek-thinking.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skillopt/patches/skillopt-evidence-hook.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skillopt/patches/skillopt-officeqa-tool-json-repair.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skillopt/patches/skillopt-officeqa-bounded-recovery.patch"
```

The tool-JSON patch accepts literal JSON control characters emitted inside
DeepSeek tool arguments but continues to reject structurally invalid JSON. The
bounded-recovery patch prevents repeated unstructured OfficeQA analysis from
consuming the entire tool-turn budget while preserving one normal repair turn.

## SkillAdaptor

```bash
git apply "$RSEBENCH_ROOT/methods/validated/skilladaptor/patches/skilladaptor-deepseek-runtime.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skilladaptor/patches/skilladaptor-evidence-hook.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skilladaptor/patches/skilladaptor-webshop-static-overlay.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skilladaptor/patches/skilladaptor-core1-calibration.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skilladaptor/patches/skilladaptor-lexical-fault-dedup.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skilladaptor/patches/skilladaptor-clean-qualification.patch"
```

The calibration patch fixes the eight-step WebShop smoke runtime, optional
file-backed task context, paired-harness ownership of held-out evaluation, and
non-fatal per-episode provider/environment failures.

The lexical fault-dedup patch routes fault similarity through the same matcher
interface as skill retrieval. This makes `SkillAdaptor_LEXICAL_MATCHING=1`
cover both paths and avoids an unsupported embedding call when only the
DeepSeek chat API is configured.

The clean-qualification patch adds execution-failure diagnostics, per-episode
retrieval and prompt-injection audit events, the explicit WebShop lexical
threshold, and a single deterministic action-format repair request.

API credentials are read only from the untracked project `.env`; patches and
manifests contain no keys.

## SkillLearn self feedback

```bash
git apply "$RSEBENCH_ROOT/methods/validated/skilllearn_self_feedback/patches/skilllearn-deepseek-evidence.patch"
```

## SkillFlow

```bash
git apply "$RSEBENCH_ROOT/methods/validated/skillflow/patches/skillflow-deepseek-provider.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skillflow/patches/skillflow-observability.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skillflow/patches/skillflow-harbor-compat.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skillflow/patches/skillflow-worker-token-budget.patch"
git apply "$RSEBENCH_ROOT/methods/validated/skillflow/patches/skillflow-skill-discovery.patch"
```

The provider patch pins the Harbor revision, adds the DeepSeek API Harbor agent,
disables thinking for worker and patcher calls, and retains compatibility with
the pinned Harbor `ExecInput` surface. Runtime caches, jobs, virtual environments,
and credentials are not part of the patch.
The evidence patch records every native patcher provider attempt in the shared
token ledger and appends UTC timing/status evidence even when patch generation
or application fails. It does not change prompts or patch acceptance behavior.
The compatibility patch migrates both native runners to Harbor's asynchronous
`Job.create` factory required by the pinned Harbor revision; it does not alter
task order, prompts, or skill evolution logic.
The worker-budget patch passes the experiment's frozen completion-token budget
into the DeepSeek Harbor agent instead of silently hard-coding 2048 tokens.
The skill-discovery patch gives the API-backed worker the explicit mounted-skill
discovery step that native coding-agent CLIs normally perform automatically.

Each baseline directory contains a `series.yaml`. The YAML order is canonical;
its pinned hashes are verified before a checkout is accepted for an experiment.
