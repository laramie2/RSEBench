# RSEBench 项目与 N1–N4 加噪验证说明

> 面向第一次参与项目的组员。状态基准：2026-08-21 UTC。

## 1. 项目研究什么

RSEBench 研究的不是固定 agent 在一次 noisy test 上掉多少分，而是噪声是否会被 self-evolution 方法吸收到可复用 skill 中，并继续影响后续干净任务。

统一实验流程是：

```text
seed skill / empty shared-skill library
        ↓
clean 或单一 stage noisy 的 evolution tasks
        ↓
trajectory、tool observation、reward、feedback
        ↓
self-evolution baseline 更新 skill
        ↓
在同一份未被污染的 clean evaluation 上测试
```

每个比较从相同 seed skill、任务 ID、任务顺序、method seed、模型和预算开始：

- `S0`：未经当前任务流进化的 seed skill；
- `SC`：从 clean evolution evidence 得到的 skill；
- `SN`：从某一个 noise stage 的 evolution evidence 得到的 skill。

核心指标是：

```text
CEG = score(SC) - score(S0)
REG = score(SN) - score(S0)
ERG = score(SC) - score(SN)
```

Noisy evolution 和 clean evolution 的最终评测必须使用同一份未参与更新或候选筛选的 clean evaluation。

## 2. 当前 validation-v1 范围

| 领域 | Benchmark | DatasetRelease | MethodRelease | 冻结规模 |
|---|---|---|---|---:|
| Spreadsheet | SpreadsheetBench-Verified | `spreadsheetbench-verified-validation-v1` | `skillopt-spreadsheet-validation-v1` | 20/10/30 |
| Document QA | OfficeQA Full | `officeqa-full-validation-v1` | `skillopt-officeqa-validation-v1` | 12/12/20 |
| Interactive | WebShop | `webshop-validation-v1` | `skilladaptor-webshop-validation-v1` | 5/5/20 |
| Longitudinal skill | SkillFlow-Task | `skillflow-tasks-validation-v1` | `skillflow-validation-v1` | 3 families × 6 ordered tasks |

SkillOpt 在 Spreadsheet 和 OfficeQA 上使用两个不同的 MethodRelease profile，因为其 clean evidence 对应的 patch series 不同，运行时不能把两者错误合并成一个共享 checkout 身份。

SkillLearnBench Self-Feedback/Teacher-Feedback 的代码、manifest 和结果保留为 diagnostic history，不再作为第四个主领域，也不能替代 SkillFlow evidence。

## 3. 当前 clean evidence 的边界

Validation-v1 冻结的是适合机制验证的输入身份，不等于四领域都已经证明跨 seed 稳定正向 clean efficacy。

| Benchmark | 当前冻结 clean 证据 |
|---|---|
| Spreadsheet | 选定 control 为 `0.3333→0.4333`；历史其他 seed 仍出现 no-update 或回退 |
| OfficeQA | 完整执行并接受更新，但 clean score 为 `0.65→0.65` tie |
| WebShop | 选定 control 为 `0.1025→0.30`；单次运行成本较高 |
| SkillFlow | HWPX family 有局部正增益；Distribution 和 Embedded 为完整执行/更新 tie |

因此后续可以比较相同冻结 clean evidence 下的 noise mechanism，但报告不能把 validation-v1 表述成四领域稳定自进化的强结论。

## 4. N1–N4 定义

N1–N4 表示噪声进入 self-evolution pipeline 的位置，不是四档强度，也不在第一阶段组合成笛卡尔积：

```text
task context → environment evidence → stored trajectory → update binding
     N1                 N2                   N3                 N4
```

| Stage | 注入边界 | 典型形式 | 必须保护 |
|---|---|---|---|
| N1 | 第一次 action 之前 | 错误 handover、先验步骤或局部提示 | objective、gold、artifact、environment、verifier |
| N2 | 执行时可见证据 | stale/near-match/conflicting evidence | gold 可达性、原始资源、official environment、verifier |
| N3 | rollout/reward 后、reflection 前 | 删除或替换 learner-visible event | reward、success、environment state、final result |
| N4 | baseline 决定更新后、updater 消费输入前 | 将 outcome 错误绑定到兼容的另一份 update evidence | evidence node、outcome、reward/verifier、更新前 skill、update trigger、updater contract |

[运行时加噪 FAQ](qa/runtime-noise-faq.md) 进一步解释 N3/N4 的运行时证据、新 baseline/benchmark 扩展方式和外部统一评测协议。

N4 只改变 node 之间的绑定，不改变 trajectory/evidence node 本身，因此与修改 evidence 内容的 N3 不同。显式 feedback 可以是一类 update evidence，但不是执行 N4 的必要条件。

冻结的 [validation-v1 matrix](../configs/validation/validation-v1.yaml) 共包含四领域 × 四 stage 的 16 个 noisy cell，其中 N4 记录的是旧 feedback/attribution 定义的机器身份，不能原地重解释。最新版 N4 必须在实现后发布新的 operator version、matrix/release；N1–N3、既有 DatasetRelease/MethodRelease 和 clean control reuse 不因这次定义修订而变化。完整实现要求见 [N4 Update-Evidence Misbinding 交接方案](architecture/2026-08-21-n4-update-evidence-misbinding-handoff.md)。

## 5. 当前项目阶段

项目当前位于 `M3：N1–N4 operator 与 runner 实现`。

- M0 taxonomy 和研究对象已确定；
- M1 四个 benchmark/baseline 的执行与更新闭环已跑通；
- M2 四个 DatasetRelease、四个 MethodRelease profile 和 validation-v1 matrix 已冻结；
- M3 需要四位成员分别实现 N1–N4 的 benchmark-specific operator、保护字段审计和具体 `CELL_RUNNERS`；
- 当前 16 个 cell 可进行结构展开，139 个 artifact locator 和四套 patch replay 已通过；
- 由于 runner 仍是 interface-only，`execution_ready=false`，正式付费 N1–N4 尚未开始，provider 调用为 0。

M3 的第一共同 gate 不是直接跑完整矩阵，而是让每个 stage 至少有一个 cell 能通过 provider-free executable preflight。

## 6. 四位成员如何协作

| Member | Stage | 固定进度页 | 实现目录 |
|---|---|---|---|
| member-1 | N1 task context | [N1 progress](progress/n1-task-context.md) | `src/rsebench/noise/stages/n1/operators/` |
| member-2 | N2 environment evidence | [N2 progress](progress/n2-environment-evidence.md) | `src/rsebench/noise/stages/n2/operators/` |
| member-3 | N3 stored trajectory | [N3 progress](progress/n3-stored-trajectory.md) | `src/rsebench/noise/stages/n3/operators/` |
| member-4 | N4 update-evidence binding | [N4 progress](progress/n4-update-feedback.md) | `src/rsebench/noise/stages/n4/` + method adapters |

成员只常规修改自己的 stage 目录和进度页。中央 matrix、release 身份和其他 stage 不能为了方便注册而被静默修改。协调者维护 [进度总览](progress/README.md)。

每次汇报至少包括 owner/status、四 benchmark gate、已完成工作、blocker、下一步、commit、结果路径、provider 调用、token 和 UTC 时间。

## 7. 运行安全

以下命令不应调用模型：

```bash
python -m rsebench.cli validation preflight \
  --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation status \
  --matrix configs/validation/validation-v1.yaml
python -m rsebench.cli validation aggregate \
  --matrix configs/validation/validation-v1.yaml
```

只有显式提供 `--confirm-provider-cost` 且 preflight 报告 `execution_ready=true` 后才能启动 paid run。当前条件未满足，run 必须在 provider call 前 fail closed。

禁止事项：

- 不根据 noisy 或 final-test outcome 重新选任务；
- 不把 zero-update、执行失败或 blocked cell 解释成 noise null effect；
- 不在未披露的情况下修改 baseline 核心更新算法；
- 不把 raw data、external clone、完整输出、credential 或 token ledger 提交到 Git；
- 不复用一个可变 checkout 并行运行需要不同 patch identity 的方法 profile。

## 8. 继续阅读

- [文档索引](README.md)
- [项目路线图](project-roadmap.md)
- [当前项目状态](reports/current/current-project-status.md)
- [Validation-v1 冻结报告](reports/current/2026-08-17-validation-v1-freeze.md)
- [Validation-v1 架构](architecture/validation-v1-architecture.md)
- [Validation runbook](operations/validation-runbook.md)
- [历史实验时间线](archive/experiment-history/README.md)
