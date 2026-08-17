# Phase 01: API pilot and initial noise

> Date range: 2026-08-12 to 2026-08-13

## Purpose

接入 DeepSeek，跑通 generation、paired evolution、OfficeQA calibration 和早期 Core-1 N1–N4 operator pilot。

## Canonical report

- [Core-1 validation status](2026-08-13-core1-validation-status.md)

## Main output roots

`outputs/runs/generation`、`pilot-a`、`paired-evolution`、`evolution-noise`、`officeqa-calibration`、`expanded-evaluation`、`difficulty-probe`、`token-ledger-smoke` 和 `incomplete`。

旧 pilot worktree 的完整 outputs 已 checksum 归档在 `outputs/archive/worktree-rsebench-pilot-20260817/`。

## Conclusion boundary

Spreadsheet 的部分 paired run 显示 clean/noisy update 分离；数学和多个其他域出现 zero-update、反向结果或执行问题。该阶段是机制候选证据，不是冻结 benchmark 结论。下一阶段专门扩大 N1 样本。
