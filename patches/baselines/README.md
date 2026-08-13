# Baseline patch order

Patches are applied from each external repository root. Core-1 calibration
patches are incremental and therefore follow the provider/evidence patches.

## SkillOpt

```bash
git apply "$RSEBENCH_ROOT/patches/baselines/skillopt-deepseek-thinking.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skillopt-evidence-hook.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skillopt-officeqa-tool-json-repair.patch"
```

The last patch accepts literal JSON control characters emitted inside
DeepSeek tool arguments but continues to reject structurally invalid JSON and
non-object arguments.

## SkillAdaptor

```bash
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor-deepseek-runtime.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor-evidence-hook.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor-webshop-static-overlay.patch"
git apply "$RSEBENCH_ROOT/patches/baselines/skilladaptor-core1-calibration.patch"
```

The calibration patch fixes the eight-step WebShop smoke runtime, optional
file-backed task context, paired-harness ownership of held-out evaluation, and
non-fatal per-episode provider/environment failures.

API credentials are read only from the untracked project `.env`; patches and
manifests contain no keys.
