# Phase 03: clean qualification and repairs

> Date range: 2026-08-13 to 2026-08-15

## Purpose

修复 OfficeQA/SkillOpt 和 WebShop/SkillAdaptor 的兼容问题，建立统一 clean-v2 control plane、baseline identity、token/timing 和 fixed-artifact replay。

## Canonical reports

- [Clean-v1 diagnostic archive](2026-08-14-clean-v1-diagnostic-archive.md)
- [Clean-v2 canaries](2026-08-14-clean-v2-canaries.md)
- [SkillLearn offline audit](2026-08-14-skilllearn-v2-offline-audit.md)
- [Clean-v2 and fixed-artifact replay](2026-08-15-clean-v2-and-fixed-artifact-replay.md)
- [Qualification hardening](2026-08-15-task5-qualification-hardening.md)
- [Portable selection release](2026-08-15-task6-portable-selection-release.md)

## Evidence

- Config: `configs/experiments/clean-v2*.yaml`
- Input: `benchmark/validation/clean_qualification_v1/` and `clean_qualification_v2/`
- Diagnostic release: `releases/diagnostic/clean-v2-canaries/manifest.json`
- Outputs: clean-v2, canaries and fixed replay roots in `registry.yaml`

## Conclusion boundary

四组 baseline 已证明可以完整执行 seed evaluation、self-evolution/update 和 clean evaluation。Spreadsheet/WebShop 的选定 canary 有正增益，OfficeQA score tie，SkillLearn 只在部分 family/seed 提升。下一阶段不再把“能运行”与“稳定提升”混为一个 gate。
