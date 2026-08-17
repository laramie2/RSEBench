# Validation-v1 runbook

## 1. Safety boundary

Bootstrap、verify、preflight、dry-run、status、aggregate 和 release audit 不得调用模型。当前 concrete `CELL_RUNNERS` 尚未实现，`execution_ready=false`，所以 paid run 必须 fail closed。

凭据只放在未跟踪 `.env`。不要在 shell history、文档、manifest、patch、result 或 token ledger 中写入 key。

## 2. Environment

```bash
python -m pip install -e '.[test]'
cp .env.example .env
python -c 'import rsebench; print(rsebench.__file__)'
```

最后一条必须解析到当前工作树 `src/rsebench/__init__.py`。如果指向旧 worktree，重新执行 editable install 后再运行任何实验。

## 3. Bootstrap and release verification

```bash
python -m rsebench.cli baselines bootstrap
python -m rsebench.cli baselines verify
```

Bootstrap 可以下载/创建 ignored source checkout。Verify 检查 upstream revision、patch series 和 release identity，不调用 provider。

## 4. Provider-free validation control

```bash
python -m rsebench.cli validation preflight \
  --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation status \
  --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation aggregate \
  --matrix configs/validation/validation-v1.yaml
```

当前预期：16 个 structural cell、139 个 artifact locator、四套 active MethodRelease patch replay、provider calls 0、`execution_ready=false`。

Preflight 必须先于 run。Status/aggregate 只读已有 attempt，不能补发模型请求。

## 5. Paid run gate

只有同时满足以下条件才能运行：

- 对应 stage operator、protected-field audit 和 concrete runner 已合并；
- preflight 报告目标 cell `execution_ready=true`；
- DatasetRelease/MethodRelease/matrix hash 与冻结身份一致；
- `.env` 中凭据有效且没有出现在 tracked diff；
- owner 在进度页登记计划 cell、预算和预估时长；
- 用户明确批准 provider cost。

正式命令是：

```bash
python -m rsebench.cli validation run \
  --matrix configs/validation/validation-v1.yaml \
  --max-parallel 16 \
  --confirm-provider-cost
```

当前不得执行该命令。首轮应由 runner 提供 bounded cell/stage 过滤，而不是直接启动 16 个 cell。

## 6. Isolation and parallelism

- 每个 cell/attempt 使用独立不可变目录；
- resume 必须匹配完整 release/matrix/runtime identity；
- source 从 pinned upstream revision 创建并重放精确 MethodRelease；
- 同一可变 checkout 默认串行；
- 使用隔离 snapshot 且不涉及共享代码修改时，不同 benchmark/cell 可以并行；
- SkillOpt Spreadsheet/OfficeQA 使用两个不同 release profile；
- family 内 SkillFlow 串行，family 间重置 shared skill library；
- clean evidence 复用，不为 16 个 noisy cell 重跑 16 次 clean。

## 7. Failure classification

终态至少区分：

```text
not_applicable
release_or_identity_failure
materialization_failure
baseline_execution_failure
provider_failure
no_update
score_tie
clean_regression
noise_effect
blocked
cancelled
```

执行失败、no-update 和 blocked 不能报告成 `noise_effect=false`。每个失败仍需 token/timing 终态记录。

## 8. Aggregation and handoff

Aggregate 读取 attempt result、audit、skill artifact hash、score、token 和 timing，不修改原始文件。汇报必须链接 run ID、cell ID、release、operator、seed、failure class 和结果目录。

运行结束后更新对应 [stage progress](../progress/README.md)，再由协调者更新总览。

## 9. Historical reproduction

旧 clean-v2、Core-1、SkillLearn 和 SkillFlow screening launcher 只用于历史重放。使用前从 [experiment history](../archive/experiment-history/README.md) 确认当时的 config、manifest、output 和结论边界；不要把它们用于定义新的 validation-v1 cell。
