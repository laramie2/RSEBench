# Phase 04: stable split and SkillLearn screening

> Date range: 2026-08-15 to 2026-08-16

## Purpose

尝试选择能稳定 clean evolution 的数据，扩大 SkillLearn family，并加固 selection reuse、exposure 和 portability。

## Canonical reports

- [SkillLearn expanded selection](2026-08-15-skilllearn-expanded-clean-selection.md)
- [Stable split blocking report](2026-08-15-stable-noise-validation-splits.md)
- [SkillLearn expansion round 2](2026-08-16-skilllearn-clean-expansion-round2.md)

## Evidence

- Config: `configs/experiments/noise-screen-v1-*.yaml` and `skilllearn-*.yaml`
- Input: `benchmark/validation/noise_screen_v1/` and `skilllearn_clean_expansion_v1/`
- Output: noise-screen and three SkillLearn roots in `registry.yaml`

## Conclusion boundary

SkillLearn 可以生成并接受 update，但跨 family/seed 稳定 clean gain 不成立；其 Self-/Teacher-Feedback 更适合作为 diagnostic weak baseline，而不是第四个主领域。下一阶段迁移至原生 shared-skill evolution 的 SkillFlow。
