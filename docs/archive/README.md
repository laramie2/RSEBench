# RSEBench 文档归档

本目录保存已经完成、被后续状态替代或仅用于历史复现的文档。归档不表示内容错误，而是表示它不再是当前执行入口。

## Categories

- `design-specs/`：解释历史设计为何被选择；
- `implementation-plans/`：记录已经完成或停止的实现步骤；
- `status-snapshots/`：保存某个时间点的项目判断；
- `experiment-history/`：按项目阶段组织报告、配置、manifest 和结果入口；
- `maintenance/`：保存仓库整理前后 inventory、checksum 边界和清理报告。

## Ordering

归档文件保留 `YYYY-MM-DD-` 前缀。同一类别按文件名排序即为时间顺序。没有日期前缀的旧文档在迁移时根据 Git 首次提交日期补齐日期。

## Reading archived material

- Archived command 可能依赖旧路径、旧 config 或已停止使用的 baseline；
- Archived status 不能覆盖 [current project status](../reports/current/current-project-status.md)；
- 机器可读 DatasetRelease、MethodRelease、registry 和 matrix 在身份冲突时优先；
- 历史路径被 release/replay locator 引用时会原位保留，即使逻辑上属于某个 archive phase；
- 历史报告中的失败、zero-update、相反结果和不完整运行必须保留，不能按后续结论重写。

## Current documentation

从 [documentation index](../README.md) 进入当前 onboarding、roadmap、architecture、protocol、operations、progress 和 current report。
