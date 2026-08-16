# RSEBench 项目路线图

> 状态基准：2026-08-16。机器可读的 active registry 和实验 YAML 是可执行事实的最终来源；本文负责解释范围、依赖关系和协作者下一步工作。

> 2026-08-16 迁移说明：第四个主 clean-validation 领域已从
> `SkillLearnBench / Self-Feedback` 调整为 `SkillFlow-Task / SkillFlow`。
> SkillLearn 的代码、manifest 和既有报告全部保留为 diagnostic history；它们不是被删除或
> 重写。SkillFlow is not frozen until two families qualify under the fixed r1/r2/r3 gate，
> 因而当前不得启动或宣称其 N1–N4 正式结果。

## 1. 项目目标

RSEBench 评测的不是固定 agent 在 noisy test 上掉多少分，而是完整的 skill self-evolution loop：

```text
Initial Skill
-> Clean/Noisy Evolution Tasks
-> Trajectories + Tool Observations + Feedback
-> Self-Evolution Method
-> Evolved Skill
-> Untouched Held-out Evaluation
```

项目需要比较三个对象：

- `S0`：未经当前任务流进化的 seed skill；
- `SC`：使用 clean evolution evidence 得到的 skill；
- `SN`：使用 noisy evolution evidence 得到的 skill。

Clean arm 与 noisy arm 必须从相同 seed skill 出发，使用相同任务 ID、method seed、模型和预算。最终 skill 在同一份未参与更新或候选选择的 clean test 上评测。这样才能回答：噪声是否被 self-evolution 方法吸收到 skill 中，并造成无增益、错误更新或 negative evolution。

项目预期验证但尚未全部证明的研究命题是：

1. 现有 baseline 在 clean 条件下能够稳定完成有效 self-evolution；
2. N1–N4 中的受控噪声会削弱部分 baseline 的 evolution gain；
3. 后续提出的 RGSE（Reliability-Guided Skill Evolution）能够降低 harmful update acceptance 和 negative evolution，同时保持 clean 能力。

当前阶段的首要任务是证明第 1 点并冻结 clean release。未达到该门槛前，不能把 zero-update 或执行失败解释成噪声无效。

## 2. 当前 Core-1 范围

当前可执行、需要共同完成的 Core-1 由四个平级领域组成。Mathematics 不属于当前 Core-1。

| 领域 | Benchmark | 当前 reference baseline | Clean-v2 规模（train/validation/test） |
|---|---|---|---:|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt | 20/10/30 |
| Document QA | OfficeQA Full | SkillOpt | 12/12/20 |
| Interactive | WebShop | SkillAdaptor | 5/5/20 |
| Longitudinal Skill Evolution | SkillFlow-Task | SkillFlow iterative shared-skill evolution | 每 family 8–9 个官方排序任务，r1/r2/r3 paired replicates |

Clean-v2 使用固定 method seed `20260813`、`20260814`、`20260815`，当前统一模型为 `deepseek-v4-flash`，`temperature=0.0`，thinking disabled。上表是 clean qualification 的正式规模，不是 Core-1 噪声筛选的小样本规模。

当前 Core-1 L2 noise screen 配置另行使用：

| Benchmark | Evolution/validation/clean test | 说明 |
|---|---:|---|
| SpreadsheetBench-Verified | 5/3/10 | Core-1 operator applicability/efficacy pilot |
| OfficeQA Full | 6/3/10 | Core-1 operator applicability/efficacy pilot |
| WebShop | 5/3/10 | Core-1 operator applicability/efficacy pilot |
| SkillLearnBench（historical diagnostic） | 1/0/4 | 保留旧 operator 与报告，不再作为第四个主领域 |

Pilot scale 只用于 operator 筛选，不能替代后续 frozen benchmark 的正式规模与统计结果。

## 3. Benchmark 介绍

### 3.1 SpreadsheetBench-Verified

SpreadsheetBench-Verified 要求 agent 根据自然语言指令修改 XLSX workbook。主要 verifier 比较指定 answer sheet/range 的单元格结果，因此 self-evolution 的核心对象是可复用的 spreadsheet 操作 skill，而不是某一个输出 workbook。

- **任务载体：** instruction、input workbook、answer workbook 和受保护目标区域；
- **执行证据：** workbook 读取/写入、公式与范围操作、保存事件、最终文件；
- **主要风险：** 错误 handover、旧版/近似 sheet、关键编辑事件缺失、错误 sheet/range 归因；
- **当前 baseline：** SkillOpt；
- **后续 native comparison：** Trace2Skill、SkillGrad。

### 3.2 OfficeQA Full

OfficeQA 基于美国财政部 Treasury Bulletin 文档，要求 agent 检索正确来源，辨别 period、unit、entity、aggregation 等条件，并返回数值答案。正式评测使用发布的 scorer；clean-v2 还记录 answer parseability、source resolution 和 typed execution failure。

- **任务载体：** question、Treasury corpus、oracle parsed pages、source metadata；
- **执行证据：** search/open/read 轨迹、retrieved text、answer 与 failure attribution；
- **主要风险：** fiscal/calendar、nominal/real、million/billion、level/change 等单轴混淆，以及冲突时期文档；
- **当前 baseline：** SkillOpt；
- **后续 native comparison：** EvoSkill。

### 3.3 WebShop

WebShop 是交互式购物环境。Agent 需要把包含多个 hard constraint 的用户目标转化为 search、商品选择和 option selection 等 action，并由官方 reward 判断是否完成任务。Self-evolution 依据 episode trajectory 定位失败步骤并修改 skill bank。

- **任务载体：** shopping goal、catalog、valid actions、product options 和 reward function；
- **执行证据：** query refinement、search result、商品点击、option selection、purchase action；
- **主要风险：** 只违反一个约束的真实 near-match 商品、排序偏置、关键 constraint event 缺失、fault localization 错位；
- **当前 baseline：** SkillAdaptor；
- **后续 comparison：** RethinkSkill，激活前仍需完成统一 adapter 与方法机制审计。

### 3.4 SkillFlow-Task

SkillFlow-Task 将专业任务组织成有官方难度顺序的 family。`base` 与
`clean_evolution` 都从独立空 skill library 开始；后者在每个任务结束后根据原生
Harbor trajectory 和 verifier result 更新同一个 shared-skill 目录，并在后续任务中读取它。

- **任务载体：** 8–9 个同 family Harbor tasks、官方排序、task Docker environment 和 verifier；
- **执行证据：** ATIF trajectory、逐任务 reward、shared-skill patch history、后续 skill read/use、token 与三级时间记录；
- **clean screening：** Batch A 先跑 r1，只有产生非空落盘 patch、后续实际使用 skill 且 `delta_late > 0` 的 family 才进入 r2/r3 confirmation；
- **正式冻结：** 至少两个 family 满足 2/3 正向、其余不负迁移、pooled full delta 为正、三次均更新且至少两次实际使用 skill；
- **当前状态：** control plane 和证据 patch 已建立，但 two families qualify 之前仍是 not frozen。

### 3.5 SkillLearnBench（diagnostic history）

SkillLearnBench 以 task family 为 self-evolution 单位。方法只能使用 acquisition instance 的 instruction、environment 和执行轨迹生成或修订 reusable skill，hidden tests 和 reference solution 不得暴露给 learner；其余 instance 使用官方 verifier 评估迁移能力。

- **任务载体：** task family、Docker/environment inputs、instruction、official verifier；
- **执行证据：** terminal/filesystem trajectory、artifact、self-reflection 或 teacher guidance；
- **主要风险：** 把 acquisition instance 的文件名、坐标、列号、版本或常量固化为不可迁移规则；
- **当前 baseline：** separated-round self-feedback；
- **N4 reference：** teacher-feedback，因为它提供显式 feedback boundary。

## 4. Baseline 方法

### 4.1 状态分层

| 层级 | 方法 | 原生/主要领域 | 文档中的状态 |
|---|---|---|---|
| 当前 reference | SkillOpt | Spreadsheet、Document QA | active；当前 clean-v2 reference |
| 当前 reference | SkillAdaptor | Interactive/WebShop | active；当前 clean-v2 reference |
| 当前 reference | SkillFlow | Longitudinal Skill Evolution | active adapter；clean family screening 中，尚未 frozen |
| 历史 diagnostic | SkillLearnBench self-/teacher-feedback | Skill Learning | 旧结果和 N1–N4 定义保留；不再作为主 clean 域 |
| 计划 comparison | Trace2Skill、SkillGrad | Spreadsheet | inactive；待统一 harness 正式验证 |
| 计划 comparison | EvoSkill | Document QA | inactive；待 shared OfficeQA manifest adapter |
| 计划 comparison | RethinkSkill | Interactive/WebShop | inactive secondary baseline |
| 计划 diagnostic | Skills-Coach、FederatedSkill | Skill-native | inactive；完成 native reproduction 后再比较 |
| 研究参考 | CoEvoSkills | Skill-native | paper-only |

`active` 只表示 registry 中已有当前执行路径，不等于已经满足 `efficacy_ready`。`inactive` 也不表示方法无效，而是尚未进入当前统一正式矩阵。

### 4.2 当前 reference baseline

**SkillOpt** 让 target model 执行任务，把 success/failure trajectory 按 minibatch 交给 optimizer 分析，再生成 skill edit；候选必须通过 native selection/validation gate 才会成为新 artifact。SpreadsheetBench 和 OfficeQA 共用其核心更新算法，但使用不同 environment adapter、工具和 verifier。RSEBench 的 patch 只处理 provider、数据/工具接口、bounded recovery、evidence hook、日志和可复现性，不应静默改变 SkillOpt 的核心优化规则。

**SkillAdaptor** 在 WebShop episode 后依次执行 Localizer、Linker 和 Reviser：先定位 actionable fault，再连接已有 skill/candidate，最后生成候选 skill bank；候选需通过原生 validation/adoption 逻辑。RSEBench 适配负责 DeepSeek provider、task ID 边界、action parser recovery、候选隔离、retrieval audit 和 N3/N4 hook，并在该 hook 边界保存原生及归一化 ordered trajectory/localized feedback，供 provider-free 资格审计重放 exact selector。

**SkillFlow** 使用官方 iterative shared-skills runner 串行执行同一 family，依据每个任务的 trajectory 与 verifier outcome 生成并应用 skill patch。RSEBench 只增加 DeepSeek provider compatibility、空初始 skill 隔离、调用级 token ledger、patch timing/status 和统一结果判定，不改变 prompt、官方任务顺序、verifier 或 patch 接受算法。

**SkillLearnBench Self-Feedback / Teacher-Feedback** 仍作为 diagnostic weak baseline 保存。此前能够更新但未稳定提升的结果，是将它移出主 clean 域的依据；历史 N1–N4 operator、运行产物和报告继续可审计，不能被当作 SkillFlow 的 clean 或 noise 证据。

### 4.3 计划接入的 comparison/diagnostic baseline

| 方法 | 方法机制摘要 | 接入要求 |
|---|---|---|
| Trace2Skill | 将 Spreadsheet trajectory 转换为 success/failure analysis，再进行 error-driven 或 combined skill-directory update | 先完成 native reproduction，再接入相同 manifest、预算和 result contract |
| SkillGrad | 从每条执行轨迹产生 textual gradient，以 momentum 累积重复信号，再进行 layer-aware skill patch | 在 Spreadsheet 前两个方法跑通后作为第三 native baseline |
| EvoSkill | 维护 skill/prompt frontier，反复提出候选并通过 evaluation 选择 | 使用 shared OfficeQA Full manifest，保留算法但替换 demo-only 数据边界 |
| RethinkSkill | Registry 中固定为 runnable secondary WebShop 方法 | 激活前完成方法机制审计、DeepSeek 路径和统一 WebShop adapter；不直接替换当前 clean qualification baseline |
| Skills-Coach | 为输入 skill 生成训练/测试任务，比较多 rollout advantage，只在多维标准改善时保留优化 skill | 用于 skill-native mechanism study，不与四域结果按样本量混合 |
| FederatedSkill | 在 SkillFlow 类任务上维护 client-specific library，并通过 merger 汇总 | 用于 federated/merger contamination 诊断 |
| CoEvoSkills | 论文描述 generator/verifier co-evolution | 当前 checkout 没有可执行方法代码；只可作 paper-only 参考或明确标注 reimplementation |

所有 baseline 都必须记录 upstream repository、固定 commit、ordered patch series、dependency/runtime fingerprint。Native reproduction 与 unified-harness result 必须分开报告。

## 5. N1–N4 加噪模型

N1–N4 描述 evolution evidence 在什么位置被污染，而不是四种任意的数据增强标签：

```text
task instance -> environment interaction -> stored trajectory -> update feedback
      N1                  N2                     N3                 N4
```

| Stage | 注入位置 | 发布形式 | 不允许改变的核心对象 |
|---|---|---|---|
| N1：task context | 第一次 action 之前 | 静态 clean/noisy task pair | 原始 objective、gold、artifact 和 verifier |
| N2：environment evidence | execution 可见的 artifact、document、catalog 或 observation source | 静态 paired artifact/evidence view | 原始解法、gold evidence 可达性和 verifier |
| N3：stored trajectory | execution 与 reward 完成后、reflection 之前 | 固定 selector/operator/seed 的 runtime mutation + replay pack | scalar reward、success、环境状态和 final answer/result |
| N4：update feedback | reflection/localization 产生后、skill revision 之前 | 固定 selector/operator/seed 的 runtime mutation + replay pack | trajectory、scalar reward、official score 和真实环境 |

N1/N2 可随 benchmark 直接分发；N3/N4 的输入依赖被测方法生成的 native trajectory/feedback，因此发布的是确定性 mutation program。每次运行必须保存 normalized `input.json`、`output.json` 和 `audit.json`，使具体变异可重放。

四个 stage 是独立实验 arm，不默认组合成 N1×N2×N3×N4。`add`、`stale`、`omit`、`replace` 是 operator 实现机制，不是额外实验维度。

## 6. 四领域加噪矩阵

本节中 SkillLearnBench 行是 2026-08-16 以前的 historical diagnostic matrix，
用于保留既有定义和结果可追溯性。它不会自动迁移为 SkillFlow noise。SkillFlow 的
N1–N4 注入边界必须在两个 clean family 正式冻结后，根据共享 skill 的纵向执行证据
重新定义和验证；当前 registry 明确为 `noise_ready: false`。

### 6.1 Operator matrix

| Benchmark | N1：task context | N2：environment evidence | N3：stored trajectory | N4：update feedback |
|---|---|---|---|---|
| SpreadsheetBench-Verified | `spreadsheet_n1_erroneous_handover`：改变一个真实约束 | `spreadsheet_n2_unlabeled_stale_sheet`：加入未标注旧版语义 sheet | `spreadsheet_n3_omit_workbook_edit`：删除一个 workbook-write event | `spreadsheet_n4_replace_blamed_range`：把归因指向同形状 decoy range |
| OfficeQA Full | `officeqa_n1_one_axis_derivation`：改变 period/unit/aggregation 中一轴 | `officeqa_n2_conflicting_period_source`：把同主题冲突时期来源排入 top-3 | `officeqa_n3_omit_oracle_source`：删除一次 oracle source open/read event | `officeqa_n4_replace_failure_axis`：替换 source/period/unit/aggregation 归因 |
| SkillLearnBench | `skilllearn_n1_brittle_handover`：诱导 acquisition instance 的固定捷径 | `skilllearn_n2_competing_stale_resource`：加入旧资源但不改变 hidden tests | `skilllearn_n3_omit_artifact_event`：删除一次 artifact-producing event | `skilllearn_n4_replace_revision_diagnosis`：把诊断目标换成同类 decoy step |
| WebShop | `webshop_n1_near_match_session`：推荐违反一个 hard constraint 的真实近邻商品 | `webshop_n2_promote_near_match`：提升近邻排序但保留可达 valid target | `webshop_n3_omit_constraint_event`：删除 required-option/query-refinement event | `webshop_n4_replace_fault_step`：把 actionable fault 定位到另一 eligible step |

### 6.2 Protected invariants

| Benchmark | N1 保护项 | N2 保护项 | N3 保护项 | N4 保护项 |
|---|---|---|---|---|
| SpreadsheetBench-Verified | 原 instruction、workbook、gold range、verifier | 全部 original sheet digest、answer workbook、verifier | reward、success、task/environment、save event、final response | trajectory、scalar reward、verifier score、result files |
| OfficeQA Full | question、answer、released sources、oracle page、official scorer | oracle 保留且可访问、answer 和 retrieval budget | reward、success、question、retrieved documents、final answer | trajectory、scalar reward、retrieved text、answer、official score |
| SkillLearnBench | instruction、official environment、hidden tests、reference solution | original resource、official environment、hidden tests | reward、success、instruction、environment、hidden tests、reference solution | trajectory、scalar reward、hidden tests、verifier details |
| WebShop | original goal、catalog、reward function、target reachability | catalog record、valid action、valid target reachability | reward、success、goal、catalog、valid actions、reward function | trajectory、scalar reward、reward/success、goal、catalog |

所有 operator 的 mutation budget 均为 1。原始 task identity、gold/verifier、scalar reward 和 untouched clean test 按阶段契约受到保护；找不到声明目标时记录 `applicable=false`，不得静默切换到其他噪声。

## 7. 实验协议与晋级门槛

### 7.1 阶段依赖

```text
baseline bootstrap/verify
-> clean engineering_ready
-> clean efficacy_ready
-> freeze clean release
-> validate N1/N2/N3/N4 independently
-> freeze promoted benchmark operators
-> comparison baselines
-> RGSE and final full experiments
```

Noise run 必须引用一个 immutable `clean_release_id`，不得在 noisy arm 中改变 clean task order、method seed、seed artifact、模型/runtime 配置或 baseline patchset。任何这类变化都需要新的 clean release 和 experiment identity。

### 7.2 Clean readiness

- `engineering_ready`：三个固定 method seed 中至少两个完成 100% 指定覆盖、没有系统性执行失败、产生语义不同的 artifact、至少接受一次通过原生 validation gate 的 update，且 evolved clean score 不低于 seed score。
- `efficacy_ready`：满足 `engineering_ready`，并且三个固定 seed 中至少两个取得严格为正的 clean gain。
- 在所有必需 Core-1 单元达到 `efficacy_ready` 并冻结 clean release 前，不开始正式 N1–N4。

Artifact 更新但 `0.0 -> 0.0` 只能作为 engineering evidence，不能描述为有效 self-evolution。Zero-update seed 必须保留在固定的三 seed 分母中。

### 7.3 Noise operator 晋级

每个 noise cell 依次通过以下门槛：

1. **Validity：** task identity、label、verifier、protected fields 和 clean test 不变；
2. **Seed calibration：** seed 不在 floor/ceiling，且没有 systemic harness failure；
3. **Applicability：** 所有需要变异的样本达到声明的覆盖率，no-op 不算 noisy example；
4. **Clean evolution：** baseline 实际接受 update，且 clean evolution 不低于 seed；
5. **Noise effect：** clean-evolved 与 noisy-evolved evidence/artifact 不同，并在 untouched clean test 上出现预注册方向的差异；
6. **Replication：** 独立 method seed/paired run 重复同方向结果，并报告 paired uncertainty。

Pilot 中的 `candidate`、`weak signal`、`null`、`opposite`、`blocked` 和 `inapplicable` 都是合法结果，必须按 typed status 报告。不能在看到 clean-test outcome 后提高 severity、替换样本或丢弃 zero-update run。

### 7.4 最终报告指标

最终主实验至少报告：

- Clean Evolution Gain（CEG）；
- Robust Evolution Gain（REG）；
- Evolution Robustness Gap（ERG = CEG − REG）；
- Negative Evolution Rate（NER）；
- seen/unseen noise 的 task-level paired 结果；
- token、模型调用、工具调用和 wall-clock 成本；
- 三 seed mean、standard deviation、paired bootstrap interval，以及适用的显著性分析。

不同领域先使用其官方 metric，再做 domain-level macro average；不能按原始样本数直接混合四个领域。

## 8. 当前状态与已知限制

截至 2026-08-16，统一 clean qualification 尚未冻结可供 N1–N4 引用的四域 release。当前状态必须按以下四层理解：

- **Execution/interface：** 统一 runner、scheduler、identity、timing、token ledger、baseline patch replay 和四域 canary 已建立；个别模型输出仍可能触发 typed interface failure，需要按 experiment identity 重跑受影响单元。
- **Clean update：** 四域主流程均已观察到可执行的 evolution/update 路径，但 accepted update 的出现率并不稳定。
- **Clean efficacy：** 尚无可公开冻结、覆盖四个 Core-1 单元的统一 `efficacy_ready` clean release。
- **Noise efficacy：** 当前没有 N1–N4 operator 完成跨 seed 稳定晋级；已有结果只能标为 candidate、weak signal、null、opposite 或 blocked。

已知领域限制：

- **Spreadsheet：** SkillOpt 可以产生 update，但独立 seed 中仍会出现 no-update 或 accepted artifact 在 clean test 上回退；
- **OfficeQA：** 主要工具参数/最终轮恢复路径已增强，但长多轮检索仍可能出现 answer recovery 或 failure-diagnostic interface 问题；
- **WebShop：** 20 条独立 episode 的 ID/解析执行链已在正式 seed 上观察到有效运行，但 SkillAdaptor episode 成本高，仍需等待完整三 seed 的 adoption/efficacy 证据；
- **SkillFlow-Task：** provider、原生 runner、结果 parser、token/patch timing 和自适应 family control plane 已就绪；当前等待两个 family 通过固定三 replicate clean 门槛，尚未 frozen；
- **SkillLearnBench（diagnostic）：** 可以生成并接受 skill update，但现有 family 上尚未得到跨 seed 稳定 clean gain；单一 `offer-letter-generator` N1 强信号仅保留为历史机制候选，不能外推为主领域结论。

详细数字应以带日期报告和 frozen release summary 为准，本文不随每个 live episode 更新。

## 9. 协作者后续任务

以下任务按依赖关系排序。前一阶段未通过时，不应通过扩大 noisy run 数量绕过门槛。

### P0：完成四域 clean qualification

- [ ] Spreadsheet / SkillOpt、OfficeQA / SkillOpt、WebShop / SkillAdaptor 继续引用各自已验证的 clean identity 与 typed evidence；
- [ ] 按 `skillflow-clean-qualification-v1` 先运行 Batch A r1；preliminary-positive 少于 2 个时才运行 Batch B；
- [ ] 只给 preliminary-positive SkillFlow family 补齐缺失的 r2/r3，直到两个 family qualified 或候选耗尽；
- [ ] 对每个 method seed 分开记录 artifact hash、accepted/rejected update、seed/evolved task score、typed failure、三层 timing 和 token coverage；
- [ ] 区分 ordinary low score、no update、clean regression 与 systemic interface failure；
- [ ] 若修复代码、patch、manifest、task 或 runtime，给受影响 cell 生成新 experiment identity，并完整重跑三个 seed；
- [ ] SkillFlow two families qualify 之前保持 not frozen；只有四个主领域都达到对应 clean 门槛后才冻结 clean release。

**交付物：** `releases/clean/<release-id>/` 下的 manifest、qualification、aggregate、timing/token summary 和 report。

### P1：首先重新验证 N1

- [ ] 所有 N1 run 引用同一个 frozen clean release；
- [ ] SkillFlow 先基于 frozen family 定义 N1 候选，不复用 SkillLearn operator，也不在 clean 结果之前创建正式 noise；
- [ ] 按 frozen task ID 和单轴 operator 运行 clean/noisy paired evolution；
- [ ] 不按 noisy outcome 选择 SkillFlow family、WebShop goal 或其他样本；
- [ ] 对 Spreadsheet/OfficeQA 的弱信号做独立重复；SkillLearn family-level candidate 只在 diagnostic history 中单独报告；
- [ ] 只有通过 validity、applicability、clean update、noise effect 和 replication 的 cell 才晋级。

**交付物：** 固定 N1 manifest、paired result、applicability audit、rejected/null log 和晋级决策。

### P2：独立验证 N2、N3、N4

- [ ] N2 验证 paired artifact/evidence view 的 label invariance、gold reachability 和 source hash；
- [ ] N3 在每个 baseline 的 `after_rollout` boundary 接入 trajectory mutation，保护 reward/success；
- [ ] N4 在 `after_feedback` boundary 接入 attribution mutation，保护 trajectory/scalar reward；
- [ ] 每次 runtime mutation 保存 `input.json`、`output.json`、`audit.json`；
- [ ] 每个 stage 独立筛选，不运行默认四阶段笛卡尔积；
- [ ] 冻结通过的 operator/version/selector/seed/budget/protected fields 和 failure policy。

**交付物：** promoted operator list、static artifacts、runtime specs、replay packs、validator report 和 rejected operator history。

### P3：接入 comparison baseline

按 native intersection 优先：

1. Spreadsheet：Trace2Skill，然后 SkillGrad；
2. Document QA：EvoSkill + shared OfficeQA Full adapter；
3. Interactive：审计并适配 RethinkSkill，保留 SkillAdaptor 作为当前 reference；
4. Skill-native comparison：在 frozen SkillFlow families 上接入 Skills-Coach、FederatedSkill；
5. CoEvoSkills 只有在代码发布或明确 reimplementation 后进入可执行比较。

每个新 baseline 必须先完成 native reproduction、identity-hook parity、DeepSeek/provider smoke、统一 result/timing/token contract，再进入 clean/noisy 正式矩阵。

### P4：冻结 RSEBench Core-1

- [ ] 冻结 split、task ID、operator、severity、seed、generator/validator version；
- [ ] 发布 static N1/N2 artifacts 和 N3/N4 runtime specs；
- [ ] 发布 clean/noisy hashes、portable locator、license/status、known limitation；
- [ ] 生成 main mixed-L2、single-noise 和 severity slice manifest；
- [ ] 保留所有 rejected candidate 和 pilot 结果，避免 outcome-driven benchmark construction。

### P5：实现 RGSE 与最终实验

Benchmark freeze 后再实现 Reliability-aware Experience Audit、Reliability-weighted Atomic Skill Induction、Conflict-aware Validation、Guarded Merge/Rollback。RGSE 不能访问 noise metadata、clean/noisy pair 或 final test。

最终运行 comparison baseline、RGSE、token/call-matched comparison、seen/unseen noise、关键消融和 skill contamination diagnostic，并生成可复现论文表格、统计报告与 benchmark card。

### 禁止事项

- 不根据 final-test outcome 选择样本或调整 severity；
- 不把无更新、执行失败或 blocked cell 报告成 noise null effect；
- 不删除 zero-update、opposite 或 clean-regression seed；
- 不在未披露的情况下修改 baseline 核心更新算法；
- 不把 raw dataset、external clone、完整 trajectory、token ledger、Docker state 或 secret 提交到 Git。

## 10. 可复现性与仓库索引

机器真源与主要说明：

- [Benchmark registry](../benchmark/registry/benchmarks.yaml)
- [Method registry](../benchmark/registry/methods.yaml)
- [Adapter registry](../benchmark/registry/adapters.yaml)
- [Noise operator registry](../benchmark/registry/noise_operators.yaml)
- [Clean-v2 matrix](../configs/experiments/clean-v2.yaml)
- [Core-1 definition](../benchmark/core1/README.md)
- [Runtime evidence interface](core1-runtime-evidence-interface.md)
- [Clean release design](superpowers/specs/2026-08-14-unified-clean-baseline-release-design.md)
- [Core-1 validation report](reports/core1-validation-status.md)
- [Expanded N1 report](reports/2026-08-13-expanded-n1-validation.md)
- [Baseline–benchmark audit](reports/baseline-benchmark-audit.md)
- [Baseline patch model](../patches/baselines/README.md)
- [SkillFlow clean design](superpowers/specs/2026-08-16-skillflow-clean-qualification-design.md)
- [SkillFlow clean implementation plan](superpowers/plans/2026-08-16-skillflow-clean-qualification.md)
- [SkillFlow frozen input manifest](../benchmark/validation/skillflow_clean_qualification_v1/input_manifest.json)

统一控制流程：

```bash
python -m rsebench.cli baselines bootstrap
python -m rsebench.cli baselines verify
python -m rsebench.cli experiment preflight \
  --matrix configs/experiments/clean-v2.yaml
python -m rsebench.cli experiment run \
  --matrix configs/experiments/clean-v2.yaml \
  --max-parallel 4 \
  --confirm-provider-cost
python -m rsebench.cli experiment status \
  --matrix configs/experiments/clean-v2.yaml
python -m rsebench.cli experiment aggregate \
  --matrix configs/experiments/clean-v2.yaml \
  --output outputs/runs/clean-v2-aggregate.json
python -m rsebench.cli release freeze \
  --run-id <run-id> \
  --matrix configs/experiments/clean-v2.yaml
```

SkillFlow 第四域使用独立但同样 cost-gated 的控制入口：

```bash
python scripts/run_skillflow_clean.py preflight
python scripts/run_skillflow_clean.py screen --dry-run
python scripts/run_skillflow_clean.py screen --confirm-provider-cost
python scripts/run_skillflow_clean.py confirm --confirm-provider-cost
python scripts/run_skillflow_clean.py aggregate
python scripts/run_skillflow_clean.py freeze
```

正式 provider call 只能由显式、带 cost confirmation 的 `experiment run` 或 SkillFlow `screen/confirm` 触发。Bootstrap、verify、preflight、dry-run、status、aggregate、freeze validation 不应调用模型。

Git 跟踪代码、registry、patch、dependency lock、frozen manifest、compact aggregate 和报告；`methods/external/`、`data/`、`outputs/`、credential 和大规模运行产物保持 gitignored。

## 11. 候选扩展

以下对象保留在 registry/历史设计中，处于 inactive 或 diagnostic 状态，不阻塞当前四域 clean qualification：

| 候选方向 | Benchmark/方法 | 当前证据与激活条件 |
|---|---|---|
| Document/visual | DocVQA | 当前只有 SkillOpt native intersection；需要可靠视觉 verifier 和第二个可信方法 |
| Document/search | SearchQA、SealQA | 分别存在 SkillOpt/EvoSkill 路径，但缺少共同的双方法正式交集 |
| Table OOD | WikiTableQuestions | 可作 OOD test；需要冻结 table-ID split 和 denotation-preserving noise |
| Mathematics | DAPO-Math、LiveMathematicianBench、AIME | DAPO 可作 calibration；当前没有足够的 native self-evolution 方法交集，不进入 Core-1 |
| Skill integrity | SkillsBench | 适合 static skill integrity diagnostic，不与四域主结果微平均 |
| Historical skill learning | SkillLearnBench Self-/Teacher-Feedback | 既有 clean/N1–N4 结果保留为 diagnostic，不作为 SkillFlow 替代证据 |
| Additional methods | Trace2Skill、SkillGrad、EvoSkill、RethinkSkill、Skills-Coach、FederatedSkill | 按第 4、9 节要求完成 native reproduction 与统一适配后逐项激活 |

新 benchmark 进入 active 范围前必须具有可靠 verifier、冻结且无泄漏的 split、至少两个可信方法交集或明确标记的 adapted baseline，并遵循相同的 clean/noise qualification、identity、timing 和成本合同。
