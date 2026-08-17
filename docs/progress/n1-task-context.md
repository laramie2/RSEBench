# N1 task-context progress

## Ownership and status

- Owner: `member-1`
- Status: `implementing`
- Last updated (UTC): `2026-08-17`
- Branch: `not-assigned`
- Latest interface commit: `7d95b87`

## Boundary and protected fields

N1 在 agent 第一次 action 之前修改 task context。必须保护原始 objective、gold、artifact、official environment 和 verifier；噪声不能把任务替换成另一个任务，也不能改变正式评分目标。

## Four-benchmark progress

| Benchmark | Operator | Unit tests | Protected-field audit | Preflight | Runner | Paid run | Result |
|---|---|---|---|---|---|---|---|
| Spreadsheet | `spreadsheet_n1_erroneous_handover` | interface tests pass | pending | structural pass | not registered | not started | none |
| OfficeQA | `officeqa_n1_one_axis_derivation` | interface tests pass | pending | structural pass | not registered | not started | none |
| WebShop | `webshop_n1_near_match_session` | interface tests pass | pending | structural pass | not registered | not started | none |
| SkillFlow | `skillflow_n1_unverified_prior_skill` | interface tests pass | pending | structural pass | not registered | not started | none |

## Completed this cycle

- 共享 N1 plugin interface 已冻结。
- 四个 operator ID 已进入 validation-v1 matrix。
- provider-free 结构检查不会启动模型调用。

## Current blockers

四领域 benchmark-specific operator 尚未实现，`CELL_RUNNERS` 尚未注册；因此不能生成可审计 noisy DatasetRelease，也不能启动付费 cell。

## Next three actions

1. 实现 Spreadsheet N1 operator 与 applicability 规则。
2. 增加 objective/gold/artifact/environment/verifier protected-field audit。
3. 注册一个 provider-free runner 并验证 replay identity。

## Decisions and coordination requests

- 单个 operator 的 mutation budget 固定为 1。
- 找不到声明目标时记录 `applicable=false`，不能退化成另一类噪声。
- 需要协调者确认首个 runner 的审查 commit 后才进入其他 benchmark 复制。

## Provider, token, timing, and result records

- Provider calls: `0`
- Prompt/completion tokens: `0/0`
- Paid runtime: `0 seconds`
- Result: none

## Handoff notes

从 [validation-v1 matrix](../../configs/validation/validation-v1.yaml) 读取 operator ID，在 `src/rsebench/noise/stages/n1/operators/` 内实现，不修改其他 stage 或中央 matrix 身份。
