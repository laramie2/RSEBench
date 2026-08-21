# N1–N4 协作进度总览

> 最后更新：2026-08-21 UTC
>
> 当前共同里程碑：每个 stage 至少注册一个能够通过 provider-free preflight 的具体 runner。

本目录是四位成员的人工进度汇报入口，不替代 [validation-v1 matrix](../../configs/validation/validation-v1.yaml)、运行状态文件或 Git commit。可执行状态发生冲突时，以机器可读事实为准。

## Stage overview

| Stage | Owner | Status | Progress page | Current blocker |
|---|---|---|---|---|
| N1 task context | member-1 | `implementing` | [N1](n1-task-context.md) | benchmark-specific operator 与 `CELL_RUNNERS` 尚未注册 |
| N2 environment evidence | member-2 | `implementing` | [N2](n2-environment-evidence.md) | immutable clean/noisy artifact 与 `CELL_RUNNERS` 尚未注册 |
| N3 stored trajectory | member-3 | `implementing` | [N3](n3-stored-trajectory.md) | method-specific runtime selector/operator adapter 尚未实现 |
| N4 update-evidence binding | member-4 | `designing` | [N4](n4-update-feedback.md) | update-conditioning contract、before-update adapter 与 decoy bank 尚未实现 |

## Shared state

- DatasetRelease、MethodRelease、插件目录和精确 4×4 matrix 已冻结。
- 16 个 cell 的结构检查可展开，139 个本地 artifact locator 已验证。
- 当前 `CELL_RUNNERS` 仍是 interface-only，因此 `execution_ready=false`。
- 当前阶段没有新的正式付费 N1–N4 结果；provider 调用为 0。
- 最新版 N4 已改为 updater 调用前的 outcome→evidence misbinding；冻结的 `validation-v1` N4 仍保留旧身份，待实现后另发 versioned release。

## Reporting rules

- stage 状态变化、出现 blocker、启动付费运行或得到结果时立即更新对应页面；
- 连续开发期间至少每个活跃工作日结束前更新一次；
- 成员只常规修改自己负责的 stage 文件，协调者维护本总览；
- 不粘贴大段原始日志，只链接 commit、matrix cell、结果和 token/timing 记录；
- blocked 必须写明阻塞条件、影响范围、已尝试措施和解除条件；
- 共同里程碑完成后，将总览和四份 stage 页面复制到 `archive/YYYY-MM-DD-<milestone>/` 形成只读快照。

## Status vocabulary

只使用：`not_started`、`designing`、`implementing`、`preflight_ready`、`running`、`validated`、`blocked`。百分比不能替代具体 gate。
