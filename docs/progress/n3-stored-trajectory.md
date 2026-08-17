# N3 stored-trajectory progress

## Ownership and status

- Owner: `member-3`
- Status: `implementing`
- Last updated (UTC): `2026-08-17`
- Branch: `not-assigned`
- Latest interface commit: `7d95b87`

## Boundary and protected fields

N3 在 rollout 和 reward 已完成、reflection 尚未开始时修改交给 learner 的 stored trajectory。必须保护 scalar reward、success、environment state 和 final result。

## Four-benchmark progress

| Benchmark | Operator | Unit tests | Protected-field audit | Preflight | Runner | Paid run | Result |
|---|---|---|---|---|---|---|---|
| Spreadsheet | `spreadsheet_n3_omit_workbook_edit` | interface tests pass | pending | structural pass | not registered | not started | none |
| OfficeQA | `officeqa_n3_omit_oracle_source` | interface tests pass | pending | structural pass | not registered | not started | none |
| WebShop | `webshop_n3_omit_constraint_event` | interface tests pass | pending | structural pass | not registered | not started | none |
| SkillFlow | `skillflow_n3_omit_skill_use_event` | interface tests pass | pending | structural pass | not registered | not started | none |

## Completed this cycle

- 共享 runtime mutation interface 与 replay-pack 边界已冻结。
- 四个 operator ID 已进入 validation-v1 matrix。
- selector/operator/seed 必须进入 runtime identity。

## Current blockers

缺少四种方法的 trajectory selector/operator adapter；尚不能证明 mutation 后 reward、result 和真实环境状态保持不变。

## Next three actions

1. 明确 runtime replay pack 的 input/output/audit 字段。
2. 实现 SkillOpt stored-trajectory hook。
3. 增加 reward/result/environment identity 断言并注册 provider-free runner。

## Decisions and coordination requests

- mutation 只作用于 learner-visible trajectory，不回写真实环境。
- 找不到目标事件时必须 fail closed 为 `applicable=false`。
- 首个 SkillOpt adapter 通过后再提取其他 baseline 的共同接口。

## Provider, token, timing, and result records

- Provider calls: `0`
- Prompt/completion tokens: `0/0`
- Paid runtime: `0 seconds`
- Result: none

## Handoff notes

在 `src/rsebench/noise/stages/n3/operators/` 内实现 selector/operator；method-specific hook 需通过 MethodRelease 身份重放，不能直接修改共享外部 checkout。
