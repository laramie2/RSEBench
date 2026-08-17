# N2 environment-evidence progress

## Ownership and status

- Owner: `member-2`
- Status: `implementing`
- Last updated (UTC): `2026-08-17`
- Branch: `not-assigned`
- Latest interface commit: `7d95b87`

## Boundary and protected fields

N2 修改 agent 执行过程中可见的 environment evidence。必须保护 gold reachability、original resource、official environment 和 verifier；加入冲突证据后原任务仍须可完成。

## Four-benchmark progress

| Benchmark | Operator | Unit tests | Protected-field audit | Preflight | Runner | Paid run | Result |
|---|---|---|---|---|---|---|---|
| Spreadsheet | `spreadsheet_n2_unlabeled_stale_sheet` | interface tests pass | pending | structural pass | not registered | not started | none |
| OfficeQA | `officeqa_n2_conflicting_period_source` | interface tests pass | pending | structural pass | not registered | not started | none |
| WebShop | `webshop_n2_promote_near_match` | interface tests pass | pending | structural pass | not registered | not started | none |
| SkillFlow | `skillflow_n2_stale_same_family_artifact` | interface tests pass | pending | structural pass | not registered | not started | none |

## Completed this cycle

- 共享 N2 static plugin interface 已冻结。
- 四个 operator ID 已进入 validation-v1 matrix。
- clean/noisy artifact 的身份必须通过 hash 绑定。

## Current blockers

四领域 immutable clean/noisy artifact materialization 和 protected-resource audit 尚未实现，`CELL_RUNNERS` 尚未注册。

## Next three actions

1. 实现 Spreadsheet stale-sheet materialization。
2. 验证 original workbook 与 verifier 的 byte/hash identity。
3. 注册一个 provider-free runner 并验证 locator portability。

## Decisions and coordination requests

- 正确证据必须保持可达，不能用 N2 隐式改写 gold。
- noisy artifact 必须与 clean artifact 分隔存储。
- 需要与 N1 owner 对齐静态 DatasetRelease 的共同字段，但不得共享 operator 实现。

## Provider, token, timing, and result records

- Provider calls: `0`
- Prompt/completion tokens: `0/0`
- Paid runtime: `0 seconds`
- Result: none

## Handoff notes

从 [validation-v1 matrix](../../configs/validation/validation-v1.yaml) 读取 operator ID，在 `src/rsebench/noise/stages/n2/operators/` 内实现，并记录 clean/noisy artifact hash 与 applicability audit。
