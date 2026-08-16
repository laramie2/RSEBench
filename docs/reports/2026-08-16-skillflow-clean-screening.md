# SkillFlow clean 样本筛选与冻结报告

日期：2026-08-16

## 结论

SkillFlow 已经能够在当前 DeepSeek 接口下完整执行“完成任务 → 生成/更新 skill → 后续任务读取 skill”的自进化闭环。最终冻结 `HWPX-Document-Automation` 的前 6 个有序任务，作为 skill 领域后续 N1–N4 验证的 clean 样本。

三次可比较运行的 full delta 分别为 `+1/6`、`0`、`+1/6`，满足预先采用的门槛：2/3 次正增益、3/3 次非负、3/3 次产生有效 patch，且 3/3 次均在后续任务中实际读取了 skill。冻结身份见 `benchmark/validation/skillflow_clean_qualification_v1/noise_validation_selection.json`。

这是一组通过 clean screening 选出的验证样本，不应把其 clean 增益当作 SkillFlow 在总体任务分布上的无偏效果估计。它的用途是提供一个可运行、可更新、已有固定 clean 对照的噪声机制验证环境。

## 固定运行设置

| 项目 | 设置 |
|---|---|
| Benchmark | SkillFlow Tasks |
| Baseline | SkillFlow iterative shared skills |
| Family | `HWPX-Document-Automation` |
| 模型 | `deepseek-v4-flash` |
| Thinking | disabled |
| Worker temperature | 0.0 |
| Worker max turns | 60 |
| Worker max completion | 8192 tokens |
| Patcher temperature | 0.2 |
| Patcher max steps / tokens | 60 / 8192 |
| Harbor 并发 | family 内串行，`n_concurrent_trials=1` |
| SkillFlow upstream | `7b49ff5a7e26cd7706e959bfa0dba4746d18440d` |
| 兼容 patch fingerprint | `e329b830e2a65748f5fc8736a2dd7f56781a28f400281b9ee608a85c98aca875` |

## 冻结任务

以下 6 个任务必须保持顺序不变，因为 SkillFlow 的 shared skill 状态按任务顺序累积：

1. `hwpx-supplier-contact-sheet`
2. `hwpx-event-announcement`
3. `hwpx-clinic-intake-summary`
4. `hwpx-project-proposal`
5. `hwpx-training-feedback`
6. `hwpx-safety-audit-brief`

`hwpx-renewal-playbook-update` 被排除，因为完整 family 的 r1 中出现了 `1→0` 的负迁移。`hwpx-inventory-report` 被排除，是为了让 r1、r2、r3 都能投影到严格相同的 6-task 有序前缀，而不是因为该任务自身失败。

## 三次 clean 证据

| Replicate | Base | Evolution | Full delta | Late delta | 前缀 patch | 后续读取 skill |
|---|---|---|---:|---:|---:|---:|
| r1 | `[1,1,1,1,1,0]` | `[1,1,1,1,1,1]` | +0.1667 | +0.2000 | 6/6 | 5/5 |
| r2 | `[1,1,1,1,1,0]` | `[1,1,1,1,1,0]` | 0 | 0 | 6/6 | 5/5 |
| r3 | `[1,1,1,1,1,0]` | `[1,1,1,1,1,1]` | +0.1667 | +0.2000 | 6/6 | 5/5 |

三次的 6 个 Harbor task checksum 逐项一致。r1 来自 8-task 原始序列，r2/r3 来自 7-task 候选序列；三者的前 6 个任务、顺序和运行配置完全相同。由于 family 内严格串行，位于前缀之后的任务不可能影响前缀内已有结果，所以该前缀投影具有因果合法性。

| Replicate | Base 前缀耗时 | Evolution 前缀耗时 |
|---|---:|---:|
| r1 | 427.19 s | 376.24 s |
| r2 | 392.10 s | 341.50 s |
| r3 | 307.16 s | 400.55 s |

冻结 selection 保存 stage 级开始、结束与耗时；原始 arm evidence 保存每个 task 的 agent、verifier 和 patch 耗时；各 attempt 的 `timing/` 目录保存 run/stage/task 三级事件。

额外执行过一次诊断性 base，结果为 `[1,1,1,1,1,1]`。其 evolution 因正增益在数学上已不可能而停止。这条证据不替换冻结的 r1–r3，但说明模型服务即使在 temperature 0 下仍可能出现输出差异；后续噪声实验必须固定并复用这里记录的 clean 对照，禁止不断重跑 clean 直到出现有利结果。

## 其他 family 的筛选结果

| Family | 结果 | 判断 |
|---|---|---|
| Document Fraud Detection | base/evolution 均为 8/8；8/8 patch、7/7 后续 skill 读取 | 闭环有效，但 base ceiling，无提升空间 |
| Operational Recovery Planning | 官方 ranking 引用一个缺失任务 | 输入无效，未调用模型 |
| HWPX Document Automation（完整 8-task） | safety `0→1`，renewal `1→0`，净增益 0 | 存在正迁移和负迁移，完整 family 不冻结 |
| SEC-13F Financial Analysis | evolution 的 `cross-quarter-reconciliation` 达到 60-turn 上限 | 运行不完整，不冻结 |
| OCR Data Extraction | base 的 nested-fuel、evolution 的 pharmacy 达到 60-turn 上限 | 运行不完整，不冻结 |
| Cross-Format Data Reconciliation | base 8/8 | base ceiling，停止 evolution |

因此，SkillFlow 本身已经证明能更新和复用 skill；未入选 family 的主要问题是 ceiling、任务复杂度触发 turn cap、输入缺失或负迁移，而不是统一的接口故障。

## 运行与资源记录

本轮正式筛选、部分停止的诊断运行、HWPX 确认及最终 semantic smoke 合计记录：

- Provider calls：1,885
- Prompt tokens：19,324,146
- Completion tokens：774,852
- 总 tokens：20,098,998
- Token 观测覆盖率：100%

其中正式/部分 family 筛选为 1,242 calls，HWPX 候选与诊断为 620 calls，最终 semantic smoke 为 23 calls。中途一次 HWPX 复验先遇到单任务 60-turn 上限，随后根分区满导致 Docker Compose 级联失败；该次被标记为无效。清理 6.7 GB pytest 临时目录并通过 Docker 探针后，后续运行恢复正常。

## 后续 N1–N4 使用约束

1. 以冻结 manifest 中的 6 个 task ID、顺序、task hash、runtime 和 baseline fingerprint 为唯一身份。
2. clean 对照直接复用 r1–r3，不因新噪声结果重新抽取 clean。
3. 每种噪声必须在同一任务顺序上运行，并分别记录 patch、skill 读取、逐任务 reward、时间和 token。
4. 将“执行有效性”和“噪声效应”分开：任何 task exception、缺失 verifier、缺失 patch 或 token 覆盖率不足都判为无效运行，不计作噪声无效。
5. 额外的 base-ceiling 诊断必须作为限制条件随结果报告，避免夸大 clean 稳定性。

## 第二个独立 family 的扩展筛选

在冻结 HWPX 后，又按相同 runtime、相同 6-task 有序前缀和相同有效性规则，筛完了其余 12 个当时尚未验证且可构造前缀的候选。没有任何候选达到 r1 preliminary-positive，因此没有启动选择性的 r2/r3 复验，也没有冻结第二个 family。

| Family | Base | Evolution | 结论 |
|---|---|---|---|
| Sales Pivot Analysis | `[0]` 后中断 | 未运行 | base 第 2 题超 60 turns |
| Compensation Scenario Modeling | `[0,0,0,0,0,0]` | `[0,0,0,0,0,0]` | 完整闭环但无增益 |
| Weighted Risk Assessment | `[0,0,0,0,0,0]` | `[0,0,0]` 后中断 | evolution 第 4 题超 60 turns |
| Distribution Center Auditing | `[1,1,1,1,1,0]` | `[1,1,1,1,1,0]` | 完整闭环但无增益 |
| PPT Formatting Optimization | 首题中断 | 未运行 | base 首题超 60 turns |
| Embedded Data Repair | `[1,0,1,1,0,1]` | `[1,0,1,1,0,1]` | 完整闭环但无增益 |
| Production Capacity Planning | `[0,0,0,0,0,1]` | `[0,0,0]` 后中断 | evolution 返回非法 tool JSON |
| Inventory & Finance Integration | `[1,1,1,0,0,0]` | `[1]` 后中断 | evolution 第 2 题超 60 turns |
| DMAIC Quality Analysis | `[0,0,0,0,0,0]` | `[0,0,0,0,0,0]` | 完整闭环但无增益 |
| Healthcare Cost Benefit Analysis | `[0,0,1,1,0]` 后中断 | 未运行 | base 第 6 题超 60 turns |
| Industry Correlation Analysis | `[1,1,1,1,1,1]` | 未运行 | base ceiling |
| Medical Data Standardization | `[0,0,0,0,0,0]` | `[0,0,0,0,0,0]` | 完整闭环但无增益 |

扩展筛选还发现 `Financial-Statement-Rolling` 与 `Supply-Chain-Replenishment` 的官方目录含未进入 ranking 的额外任务；连同此前缺失 ranking 任务的 `Operational-Recovery-Planning`，这 3 个 family 按输入合同判为无效，不调用模型。

至此 20 个官方 family 均已归类：1 个合格（HWPX）、3 个 base ceiling、5 个完整但无正增益、8 个运行不完整、3 个输入无效。当前证据不支持为了凑足两个 family 而继续重采样；在不修改协议的前提下，SkillFlow 后续 N1–N4 应只使用已冻结 HWPX。若项目仍强制要求第二个独立 family，需要显式选择新的研究设计，例如修改 turn/runtime 合同后重新筛选，或改用 task-level/prefix 选择规则，并将其标记为新的实验协议。

本次 12-family 扩展筛选共记录 1,928 次 provider 调用、18,770,571 prompt tokens、935,129 completion tokens，总计 19,705,700 tokens，观测覆盖率 100%。各 attempt 的 run/stage 时间总和为 10,798.30 秒；逐 family 耗时、token 与判定保存在 `benchmark/validation/skillflow_clean_qualification_v1/second_family_screening_results.json`。
