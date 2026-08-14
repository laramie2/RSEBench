# Baseline patch order

Patches are applied from each external repository root. Core-1 calibration
patches are incremental and therefore follow the provider/evidence patches.

## SkillOpt

```bash
git apply "$RSEBENCH_ROOT/patches/baselines/skillopt/skillopt-deepseek-thinking.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skillopt/skillopt-evidence-hook.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skillopt/skillopt-officeqa-tool-json-repair.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skillopt/skillopt-officeqa-bounded-recovery.patch"
```

The tool-JSON patch accepts literal JSON control characters emitted inside
DeepSeek tool arguments but continues to reject structurally invalid JSON. The
bounded-recovery patch prevents repeated unstructured OfficeQA analysis from
consuming the entire tool-turn budget while preserving one normal repair turn.

## SkillAdaptor

```bash
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor/skilladaptor-deepseek-runtime.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor/skilladaptor-evidence-hook.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor/skilladaptor-webshop-static-overlay.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor/skilladaptor-core1-calibration.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor/skilladaptor-lexical-fault-dedup.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor/skilladaptor-clean-qualification.patch"
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
git apply "$RSEBENCH_ROOT/patches/baselines/skilllearn_self_feedback/skilllearn-deepseek-evidence.patch"
```

Each baseline directory contains a `series.yaml`. The YAML order is canonical;
its pinned hashes are verified before a checkout is accepted for an experiment.
