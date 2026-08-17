# N4 update-feedback progress

## Ownership and status

- Owner: `member-4`
- Status: `implementing`
- Last updated (UTC): `2026-08-17`
- Branch: `not-assigned`
- Latest interface commit: `7d95b87`

## Boundary and protected fields

N4 在 feedback/localization 已产生、skill revision 尚未执行时修改 learner 使用的归因或诊断。必须保护完整 trajectory、scalar reward、official score 和真实 environment state。

## Four-benchmark progress

| Benchmark | Operator | Unit tests | Protected-field audit | Preflight | Runner | Paid run | Result |
|---|---|---|---|---|---|---|---|
| Spreadsheet | `spreadsheet_n4_replace_blamed_range` | interface tests pass | pending | structural pass | not registered | not started | none |
| OfficeQA | `officeqa_n4_replace_failure_axis` | interface tests pass | pending | structural pass | not registered | not started | none |
| WebShop | `webshop_n4_replace_fault_step` | interface tests pass | pending | structural pass | not registered | not started | none |
| SkillFlow | `skillflow_n4_replace_patch_attribution` | interface tests pass | pending | structural pass | not registered | not started | none |

## Completed this cycle

- 共享 N4 runtime feedback interface 已冻结。
- 四个 operator ID 已进入 validation-v1 matrix。
- N4 不允许修改 scalar reward 或 official score。

## Current blockers

四种 baseline 的 feedback/update boundary adapter 尚未实现；当前不能把替换后的 attribution 注入原生 skill revision 流程。

## Next three actions

1. 映射 SkillOpt、SkillAdaptor 和 SkillFlow 的 feedback/update hook。
2. 实现 SkillOpt blamed-range/failure-axis attribution replacement。
3. 验证 trajectory/reward/official-score identity 并注册 provider-free runner。

## Decisions and coordination requests

- 只替换 learner-visible diagnosis target，不修改真实执行证据。
- N4 结果必须同时保留原 feedback、noisy feedback 和 mutation audit。
- SkillFlow patch attribution 的最小替换单元需在首个实现审查中确认。

## Provider, token, timing, and result records

- Provider calls: `0`
- Prompt/completion tokens: `0/0`
- Paid runtime: `0 seconds`
- Result: none

## Handoff notes

在 `src/rsebench/noise/stages/n4/operators/` 内实现通用 mutation；baseline adapter 通过对应 MethodRelease patch/hook 接入，不能改写原始 reward 或 verifier。
