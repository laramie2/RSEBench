# N1–N4 协作者工作流

## 1. Ownership model

| Owner | Code ownership | Progress ownership |
|---|---|---|
| member-1 | `src/rsebench/noise/stages/n1/operators/` | `docs/progress/n1-task-context.md` |
| member-2 | `src/rsebench/noise/stages/n2/operators/` | `docs/progress/n2-environment-evidence.md` |
| member-3 | `src/rsebench/noise/stages/n3/operators/` | `docs/progress/n3-stored-trajectory.md` |
| member-4 | `src/rsebench/noise/stages/n4/operators/` | `docs/progress/n4-update-feedback.md` |
| coordinator | shared validation contract and dashboard | `docs/progress/README.md` |

一位成员可以为四个 benchmark 实现同一个 stage，但不能顺便修改其他 stage。共享接口确需变化时，单独提交 contract change，由四位 owner 共同审查。

## 2. Branch and commit discipline

- 每个 stage 使用独立 branch；
- 一个 commit 只包含一个 operator、一个 adapter 或一类审计；
- 不直接编辑 external source 作为最终修复，改动必须形成 tracked MethodRelease patch；
- 不在 PR/preflight 中设置真实 provider key 或启动 paid call；
- 不修改 frozen matrix ID 来绕过缺失 runner；
- 不提交 raw data、external checkout、完整 output、credential 或本地 virtualenv。

## 3. Required development gates

每个 operator 按顺序完成：

1. operator contract/unit test；
2. benchmark-specific applicability；
3. mutation budget；
4. protected-field audit；
5. clean identity path；
6. artifact/replay-pack schema；
7. concrete runner registration；
8. provider-free preflight；
9. bounded paid validation；
10. progress/result handoff。

不能用单次 paid result 代替前八个 gate。

## 4. Progress reporting

状态只使用 `not_started`、`designing`、`implementing`、`preflight_ready`、`running`、`validated`、`blocked`。

每次状态变化、blocker、paid-run start 和 terminal result 都更新 stage 页面。连续开发至少每日更新一次。成员不常规编辑总览，避免四人冲突；协调者根据已合并 stage 状态更新 dashboard。

每个共同里程碑结束后复制当前五份页面到 `docs/progress/archive/YYYY-MM-DD-<milestone>/`，形成只读 snapshot。

## 5. Handoff checklist

每次提交给下一位成员或协调者时提供：

```text
branch and commit
stage and operator ID
benchmark and matrix cell
DatasetRelease and MethodRelease
unit/static/preflight commands and results
protected-field audit result
applicability/failure behavior
output or replay-pack locator
provider calls and token coverage
UTC start/end/duration
current blocker
next concrete action
```

缺少 release identity、审计或 timing 的结果不能进入正式 aggregate。

## 6. Conflict handling

- 同一 baseline 需要不同 patch profile 时使用隔离 source snapshot；
- 同一 tracked file 冲突由 file owner 先合并，其他成员 rebase；
- 发现 matrix/release 设计问题时停止目标 cell，不在 operator 分支原地改 release；
- blocker 影响其他 stage 时写入总览并指定解除条件；
- operator 语义必须变化时发布新 version，不复用旧 ID 掩盖差异。

## 7. Review checklist

Reviewer 确认：

- 改动仅在声明 ownership 范围；
- clean/noisy identity 和 protected fields 有测试；
- failure 不会被错误聚合为 null effect；
- 无 secret、绝对机器路径或未登记 provider 行为；
- token/timing/result 合同完整；
- 进度页与代码实际状态一致；
- provider-free preflight 为 0 model calls。
