# Phase 02: expanded N1

> Date: 2026-08-13

## Purpose

扩大 Spreadsheet、OfficeQA、WebShop 和 SkillLearn 的 N1 样本，检验早期单样本信号是否稳定。

## Canonical report

- [Expanded N1 validation](2026-08-13-expanded-n1-validation.md)

## Evidence

- Input: `benchmark/validation/n1_expanded/`
- Aggregate: `outputs/runs/n1-expanded-20260813/aggregate.json`
- Additional Core-1 roots listed in `registry.yaml`

## Conclusion boundary

扩大样本解决了单样本解释问题，但 N1 没有在四领域稳定成立。Spreadsheet/OfficeQA 仅弱或不稳定，WebShop 当时受 baseline 运行问题影响，SkillLearn 只有单一 family 强信号。下一阶段先资格化 clean baseline。
