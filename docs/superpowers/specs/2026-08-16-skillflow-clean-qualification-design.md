# SkillFlow 主领域 clean 自进化资格筛选设计

日期：2026-08-16

## 1. 背景与决策

RSEBench 当前需要在四个领域中先冻结一组能够在 clean 条件下稳定完成自进化、并产生可重复能力提升的数据，之后才在完全相同的数据和初始状态上验证 N1–N4 噪声。

此前第四领域使用 `SkillLearnBench / Self Feedback`。现有扩大样本实验表明：该组合能够执行 skill revision，但 clean 能力提升只在少数 family 中出现，且 SkillLearnBench 论文中的 Self Feedback 本身也是弱、混合效果的 benchmark baseline。继续扩大这一路径只能增加弱基线筛选量，不能改善后续噪声效应的可解释性。

本设计作出以下决策：

1. 第四个主验证领域由 `SkillLearnBench / Self Feedback` 替换为 `SkillFlow-Task / SkillFlow iterative shared-skill evolution`。
2. SkillLearnBench 的历史 clean 与 N1 结果继续保留，定位调整为 diagnostic weak baseline，不删除、不改写，也不再启动计划中的五个 Self Feedback family 扩展运行。
3. SkillFlow-Task 的 clean family 必须先经过独立筛选和三次重复确认；只有合格 family 才能冻结并进入后续 N1–N4 验证。
4. 本轮只解决 clean 原生流程、资格筛选和可复现冻结，不同时设计或调优 N1–N4 具体算子。

SkillFlow 官方论文和仓库是本设计中原生协议的权威来源：

- 论文：<https://arxiv.org/html/2604.17308v1>
- 代码：<https://github.com/ZhangZi-a/SkillFlow>
- 数据：<https://huggingface.co/datasets/zhang-ziao/SkillFlow-Task>

## 2. 研究问题与解释边界

本轮只回答：

> 在固定 DeepSeek 模型、固定 SkillFlow agent wrapper 和固定 family 顺序下，哪些 SkillFlow-Task family 能够让 iterative shared-skill evolution 相对无共享 skill 的 base 条件产生稳定的 clean completion gain？

本轮不回答：

- SkillFlow 是否对所有模型或全部 20 个 family 普遍有效；
- DeepSeek 是否是 SkillFlow 论文中表现最好的模型；
- 哪一种 N1–N4 噪声最有效；
- clean 筛选出的 family 是否可以直接代表完整 SkillFlow benchmark；
- SkillLearnBench 是否没有研究价值。

合格 family 的正确称呼是 `clean-efficacy-qualified validation slice`，不能称为完整 benchmark 上的普适自进化结论。所有被筛选但不合格的 family 及其零增益、负增益或无效运行都必须保留在筛选分母和报告中。

## 3. Benchmark、baseline 与实验单位

### 3.1 Benchmark

使用 `SkillFlow-Task`：20 个 workflow family，共 166 个 Harbor 任务。每个 family 包含 8–9 个按官方难度顺序排列的任务；本地数据必须逐文件校验，并以 `ALL_TASK_DIFFICULTY_RANKING.json` 为顺序权威来源。

一个 **family sequence** 是本实验的最小自进化数据单位。不得拆散后跨 family 拼接，也不得依据单个任务的已观察结果重新排序。

### 3.2 两个 paired arm

每个 family replicate 比较两个仅在共享 skill 更新上不同的 arm：

| Arm | 初始状态 | 任务间更新 | 后续任务可见内容 |
|---|---|---|---|
| `base` | 空 shared skill library | 不生成、不应用 skill patch | 无历史共享 skill |
| `clean_evolution` | 同样为空 | 每个任务结束后，根据执行轨迹、verifier/rubric 反馈生成并应用 skill patch | 当前 family 之前任务累积的共享 skill |

两个 arm 必须固定相同的：

- model identifier 与 provider endpoint 类型；
- agent system prompt、tool interface、最大 turns 和 token budget；
- Harbor 与任务容器版本；
- family、任务顺序、任务数据和 verifier；
- internet policy、环境变量白名单和资源限制；
- 结果收集、计时和 token ledger 逻辑。

`clean_evolution` 沿用官方 Agentic Lifelong Learning 协议：同一 family 内任务严格串行，任务结束后才更新共享 library。不得把未来任务信息、reference solution 或 verifier 实现泄漏进 skill patch prompt。

### 3.3 Replicate，而非伪确定性 seed

当前 DeepSeek API 路径没有可靠、已验证的采样 seed contract。虽然 agent 请求使用低温或零温，provider 运行仍可能非确定。因此本设计使用 `replicate_id = r1/r2/r3`，不把它们描述为严格确定性的 method seeds。

每个 replicate 都从独立的空 skill 目录开始。不同 replicate、family 和 arm 的输出目录必须物理隔离，不能续接或复用上一次生成的 skill。

## 4. 候选 family 与自适应筛选顺序

候选优先级只用于节省筛选成本，不作为最终有效性证据。第一、二批 family 依据 SkillFlow 论文 family-level heatmap 中跨多个模型出现正迁移的频率选择；DeepSeek 的最终判定只使用本项目 fresh clean 运行。

### 4.1 第一批

先对以下 4 个 family 各运行一个完整 paired replicate：

1. `Document-Fraud-Detection`
2. `Operational-Recovery-Planning`
3. `HWPX-Document-Automation`
4. `SEC-13F-Financial-Analysis`

### 4.2 第二批

如果第一批 preliminary-positive family 少于 2 个，追加：

5. `OCR-Data-Extraction`
6. `Cross-Format-Data-Reconciliation`

### 4.3 后续扩展

目标是冻结至少 2 个正式合格 family，使 skill 领域包含约 16–18 个顺序任务，而不是再次依赖单一 family。

- 如果第一、二批得到至少 2 个 preliminary-positive family，只确认其中排名最高的 2 个。
- 如果确认后只有 1 个正式合格 family，保留它并按每批 2 个 family 继续筛选剩余数据，直到获得第 2 个正式合格 family 或 20 个 family 全部用尽。
- 如果 20 个 family 全部筛完仍不足 2 个正式合格 family，不降低门槛；应把 `DeepSeek / SkillFlow` 标为 clean efficacy blocked，并重新评估模型或 baseline。

第一批 screening replicate 在配置、代码和数据哈希未变化时可计为该 family 的 `r1`，无需重复付费运行。

## 5. 指标

### 5.1 主要效果指标

任务 1 开始前两个 arm 都没有历史 skill，因此主要效果只在任务 2 到任务末尾计算：

```text
late_completion(arm, replicate)
  = mean(task_reward[t] for t = 2..n)

delta_late(replicate)
  = late_completion(clean_evolution, replicate)
  - late_completion(base, replicate)
```

`delta_late` 是正式 clean 资格判定的主要指标。

### 5.2 原生协议辅助指标

同时报告论文原生的全 family completion：

```text
full_completion(arm, replicate)
  = mean(task_reward[t] for t = 1..n)

delta_full(replicate)
  = full_completion(clean_evolution, replicate)
  - full_completion(base, replicate)
```

还需记录：

- paired task wins、ties、losses；
- 生成、更新和删除的 skill 文件数量；
- 合法 patch 比例与 patch failure 类型；
- 任务 2 以后实际读取或调用历史 skill 的任务比例；
- 每个任务的 verifier reward、异常和执行状态；
- input/output tokens、API 调用数和可计费 token 覆盖率；
- turns、wall-clock duration 和 skill patch duration。

### 5.3 时间记录

结果文件使用三级时间记录：

1. **experiment level**：整个 screening 或 confirmation run 的开始、结束和 wall-clock duration；
2. **family-replicate-arm level**：一个 family、replicate、arm 的开始、结束和 duration；
3. **task level**：单个 Harbor task 的开始、结束、agent duration、verifier duration 和 patch duration。

时间统一使用带时区的 UTC ISO-8601；duration 使用秒。单次 API 调用时间继续保存在 token/call ledger 中，但不作为第四级汇总表。

## 6. Screening 与正式资格门槛

### 6.1 Preliminary positive

一个 screening replicate 只有同时满足以下条件才算 preliminary positive：

1. paired 两个 arm 的所有计划任务都完成并产生可解析 verifier result；
2. `clean_evolution` 至少产生一个合法、非空且实际落盘的 skill patch；
3. 任务 2 以后至少一个任务读取或调用了历史 shared skill；
4. `delta_late > 0`；
5. 运行不存在使对照失效的基础设施或接口错误。

### 6.2 正式合格

进入 confirmation 的 family 补齐 `r1/r2/r3` 三个 paired replicate。一个 family 只有同时满足以下条件才标为 `qualified`：

1. 3 次 paired replicate 的两个 arm 均完整、有效；
2. 3 次 `clean_evolution` 均产生合法、非空的持久化 skill 更新；
3. 3 次中至少 2 次在后续任务中实际使用过历史 skill；
4. 至少 2/3 次满足 `delta_late > 0`；
5. 剩余 replicate 满足 `delta_late >= 0`，不得负迁移；
6. 三次 pooled `delta_full > 0`；
7. 不存在系统性的任务环境、verifier、ID/解析或结果聚合错误。

`delta_late = 0` 不算正向 replicate。不得删除 zero-update、tie 或负增益 replicate，也不得在看到 confirmation 结果后修改门槛。

### 6.3 Invalid 与失败结果

以下情况标为 typed invalid，不进入能力增益分母，但必须保留记录：

- 容器无法构建或启动；
- 数据文件缺失或 checksum 不匹配；
- agent/tool transport 失败导致任务未实际执行；
- verifier 未运行、结果无法解析或 task ID 映射错误；
- 结果目录相互污染；
- token/time ledger 缺少必需层级。

模型完成任务但没有更新 skill、没有使用 skill、更新后不提升或发生负迁移，均是合法实验结果，不得标为 infrastructure invalid。

修复 typed invalid 问题后，只重跑受影响且输出已隔离的完整 paired replicate；不得把旧 arm 与修复后的新 arm 拼成一对。

## 7. 可复现实现要求

当前本地状态已经包含完整 SkillFlow-Task 数据、官方 base/iterative runners 和 DeepSeek adapter，但不能直接作为公开可复现 release。正式运行前必须完成：

1. 从固定 upstream commit `7b49ff5a7e26cd7706e959bfa0dba4746d18440d` 生成可重放的 SkillFlow patch series；
2. 在 patch manifest 中区分 compatibility adapter、observability changes 与任何 unified-harness adaptation；
3. 创建不含 secret 的 DeepSeek base 与 clean-evolution 配置；
4. 构建并记录 SkillFlow Harbor base image digest；
5. 固定 Python、Harbor、LiteLLM 和关键依赖版本；
6. 提供同一入口的 `preflight`、`screen`、`confirm`、`aggregate` 和 `freeze` 阶段；
7. 为任务顺序、空初始 skill、结果隔离、patch 记录、typed status、token 和三级时间字段增加离线测试；
8. 先通过 transport、structured output、tool、单任务容器和最小两任务迭代 smoke，再允许正式付费筛选。

Compatibility patch 可以修复模型接口、结构化输出、trajectory materialization、ID 解析、计时和结果记录，但不得改变 task instruction、verifier 判定、官方任务顺序或根据结果选择性接受 skill patch。任何超出兼容层的算法变化必须标为 adapted baseline，并使此前对应结果失效。

## 8. 输出与冻结产物

### 8.1 运行输出

每次运行写入独立目录：

```text
outputs/runs/<run-id>/
  run_manifest.json
  aggregate.json
  token_ledger.jsonl
  timing.json
  families/<family>/<replicate>/<arm>/
    result.json
    task_results.jsonl
    timing.json
    skill_patch_history.jsonl   # clean_evolution only
    final_skills/               # clean_evolution only
```

原始 Harbor trial、trajectory 和容器日志可以保留在 gitignored 运行目录中，但聚合结果必须能追溯到其路径和哈希。

### 8.2 冻结 manifest

正式合格后写入：

```text
benchmark/validation/skillflow_clean_qualification_v1/manifest.json
```

至少包含：

- benchmark 与 baseline 标识；
- upstream commit、patch-series hash 和主仓库 commit；
- model、provider contract 和运行参数；
- Docker image digest 与依赖锁文件 hash；
- qualified、screened-out、invalid family 列表；
- 每个 family 的官方任务顺序和逐文件/任务 hash；
- 初始空 skill 状态 hash；
- replicate IDs、运行 IDs 和原始结果索引；
- clean 指标、token 和三级时间汇总；
- qualification contract version。

同时生成中文报告，逐个列出筛选分母、运行错误、clean gain、skill usage 和最终冻结理由。

### 8.3 后续噪声复用规则

后续 N1–N4 实验必须：

- 使用冻结的 family、任务顺序、初始空 skill、模型和预算；
- 每个 noisy arm 从空 library 重新开始完整进化；
- 复用冻结 clean 结果作为对照，不把 clean 最终 library 作为 noisy 初始状态；
- 不根据 noisy 结果重新选择 family、任务或门槛；
- 单独报告这是 efficacy-qualified validation slice，而非完整 20-family benchmark 结果。

N1–N4 在 SkillFlow 的具体注入矩阵、protected information 和 promotion gate 将在 clean family 冻结后另立规格，不属于本设计的实现范围。

## 9. 仓库范围迁移

实施本设计时需要同步以下项目元数据，但不得删除历史文件：

- 将 `skillflow_tasks` 与 `skillflow` 提升为第四个主领域的 active benchmark/method；
- 将 `skilllearnbench` 与 Self Feedback 标记为 diagnostic weak baseline；
- 更新项目路线图、benchmark/method/adapter registry 和当前实验状态；
- 保留所有 SkillLearn clean/N1 manifest、报告、patch 和原始结果引用；
- 明确注明旧四领域定义被本规格对未来验证流程取代的日期和范围。

在 SkillFlow 至少获得 2 个正式合格 family 前，不得声称第四领域已经 clean frozen，也不得开始该领域的正式 N1–N4 运行。

## 10. 成本与停止规则

为避免再次出现长时间运行但不能回答 clean efficacy 的情况：

1. 任何正式任务前先完成零/低成本离线和最小 smoke；
2. 第一批只运行一个 paired replicate，不预先启动全部三次确认；
3. 只对 preliminary-positive family 补 confirmation；
4. 同一 family 内 iterative tasks 必须串行，不同 family/arm 只有在输出、Docker 和 API 限流相互隔离时才可并行；
5. 每个 family-replicate-arm 设置明确 wall-clock timeout 和 typed timeout status；
6. 如果出现同一基础设施故障，停止尚未开始的同类运行，先修复并重新 smoke；
7. 每批结束立即聚合并判断，不自动扩展到下一批；
8. 达到 2 个正式合格 family 后停止 clean 筛选，不为追求更高 gain 继续挑选。

正式付费运行前，preflight 输出应给出基于实测单任务/两任务 smoke 的 wall-clock 和 token 区间；在没有 fresh smoke 数据前不提供虚假精确的总时长承诺。

## 11. 验收标准

本设计的实现与 clean 筛选阶段只有在以下条件全部满足时完成：

1. SkillFlow upstream、compatibility patch、环境和数据可以从主仓库说明中重放；
2. base 与 clean-evolution 两个 arm 均通过离线测试和真实最小 smoke；
3. 第一批筛选按预注册顺序执行并产生完整 machine-readable 结果；
4. 所有 screened-out、invalid 和 qualified family 都留有 typed evidence；
5. 至少 2 个 family 通过三次 paired replicate 的正式资格门槛；
6. family/task manifest、clean outputs、token 与三级时间记录均被冻结并具有 hash；
7. 中文报告清楚区分执行成功、skill 更新、skill 使用、clean efficacy 和稳定性；
8. 未启动任何 SkillFlow N1–N4 正式实验，也未根据 noise outcome 选择数据。
