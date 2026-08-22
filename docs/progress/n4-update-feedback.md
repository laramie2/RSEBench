# N4 update-evidence binding progress

## Ownership and status

- Owner: `member-4`
- Status: `designing`
- Last updated (UTC): `2026-08-21`
- Branch: `docs/n4-update-evidence-definition`
- Latest design: [N4 Update-Evidence Misbinding 交接方案](../architecture/2026-08-21-n4-update-evidence-misbinding-handoff.md)

## Boundary and protected fields

N4 在 baseline 已经按照原逻辑决定调用 updater、但 updater 尚未消费输入时，保持 outcome 和 evidence node 内容不变，只把正确的 outcome→evidence 绑定替换为兼容但错误的绑定。

必须保护 trajectory/evidence node、outcome、reward/verifier、更新前 skill、update trigger 和 updater contract。显式 feedback 可以是一类 evidence node，但不是 N4 执行的前提。未触发更新的任务不进入 N4 applicability 分母，也不能被 N4 强制更新。

## Four-benchmark progress

| Benchmark | Operator | Unit tests | Protected-field audit | Preflight | Runner | Paid run | Result |
|---|---|---|---|---|---|---|---|
| Spreadsheet | `n4_update_evidence_misbinding` before SkillOpt analyst/reflection | pending | pending | pending | not registered | not started | none |
| OfficeQA | `n4_update_evidence_misbinding` before SkillOpt analyst/reflection | pending | pending | pending | not registered | not started | none |
| WebShop | `n4_update_evidence_misbinding` before SkillAdaptor revision | pending | pending | pending | not registered | not started | none |
| SkillFlow | `n4_update_evidence_misbinding` before SkillFlow patcher | pending | pending | pending | not registered | not started | none |

## Completed this cycle

- 最新版 threat model、N3/N4 边界和四领域方法映射已确定。
- 公共 operator 固定为 update-evidence misbinding，不要求 baseline 有独立 feedback attribution boundary。
- batch 内 compatible derangement 与 singleton frozen decoy-bank 策略已确定。
- matched clean/noisy、replay pack、preflight、smoke 和四领域验证实验要求已写入交接方案。

## Current blockers

`UpdateConditioningRecord`、`UpdateBindingAdapter.before_update`、四方法 adapter、decoy-bank release 和 binding replay schema 尚未实现。当前 `main` 中冻结的 `validation-v1` N4 仍是旧 feedback/attribution 定义，不能直接作为最新版 N4 runner。

## Next three actions

1. 实现公共 update-conditioning contract、protected-state 和 `before_update` hook。
2. 实现 SkillOpt、SkillAdaptor、SkillFlow adapter 及 provider-free decoy-bank freezer。
3. 发布新的 N4 operator version/matrix/release，完成四领域 provider-free smoke 后再做 paired validation。

## Decisions and coordination requests

- 只修改 outcome→evidence binding，不修改任何 evidence node 内容。
- clean/noisy 两臂都经过同一 instrumentation path，clean 使用 identity binding。
- decoy 必须 schema/role/method/domain compatible，选择规则和 assignment 在实验前冻结。
- 冻结的 `validation-v1` 不原地改写；新版 N4 使用新的 versioned identity。

## Provider, token, timing, and result records

- Provider calls: `0`
- Prompt/completion tokens: `0/0`
- Paid runtime: `0 seconds`
- Result: none

## Handoff notes

按交接方案在 `rsebench.evidence` 定义公共合同，在 `src/rsebench/noise/stages/n4/` 实现通用 binding mutation。Baseline adapter 只负责 native↔normalized 转换和 updater 边界接入；benchmark policy 只声明 compatibility。公共 operator 不得 import baseline runner，任何组件都不能改写 node、reward 或 verifier。
