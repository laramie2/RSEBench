# 协作者项目路线图文档设计

日期：2026-08-14

## 目标

在 `docs/project-roadmap.md` 中创建一份面向仓库协作者的中文入口文档。新协作者无需重新阅读全部历史计划，就应能回答以下四个问题：

1. 当前可执行范围包含哪些 benchmark 和 baseline？
2. N1、N2、N3、N4 分别在每个 benchmark 的什么位置、以什么方式加噪？
3. 一个 benchmark 单元或噪声算子进入下一阶段前需要哪些证据？
4. 项目还需要完成哪些实现和实验工作？

该文档定位为协作执行手册，不取代详细设计规格、机器可读 registry、实验报告或最终 benchmark card。

## 受众与权威边界

主要读者是了解 agent evaluation、但没有跟进本地验证历史的仓库协作者。文档使用简洁的研究术语、表格、明确的状态标签和仓库链接，不逐轮复述所有 pilot 实验。

当前以 Core-1 范围为准：

| 领域 | Benchmark | 主要 clean/noise 验证 baseline |
|---|---|---|
| Spreadsheet | SpreadsheetBench-Verified | SkillOpt |
| Document QA | OfficeQA Full | SkillOpt |
| Interactive | WebShop | SkillAdaptor |
| Skill Learning | SkillLearnBench | 分轮 self-feedback；N4 使用 teacher-feedback |

Mathematics、DocVQA、WikiTableQuestions、SearchQA、SealQA、SkillsBench、SkillFlow-Task 及其他历史候选不属于当前 Core-1 承诺范围，只放在明确标注的候选扩展附录中。

当不同来源存在差异时，文档按以下优先级取值：

1. `benchmark/registry/` 中的 active 项和可执行实验 YAML；
2. unified clean-v2 release design 与 Core-1 runtime contract；
3. 已冻结的 Core-1 operator 规格和 manifest；
4. 带日期的验证报告；
5. 早期项目总设计，仅用于说明长期意图。

该顺序保证早期提案不会覆盖后续已经冻结的配置。

## 最终文档结构

最终文档采用“协作者执行手册”结构。

### 1. 项目目标与研究命题

说明 RSEBench 评测的是完整 self-evolution loop，而不只是 noisy inference。明确比较对象包括 seed skill、在 clean evidence 上进化的 skill，以及在 noisy evidence 上进化的 skill；最终均在未参与进化和选择的 held-out data 上评测。预期研究假设与已经得到的实验结论必须分开陈述。

### 2. 当前 Core-1 benchmark

每个 benchmark 需要说明：

- 任务形式和 verifier；
- self-evolution 的基本单位；
- 当前 clean-v2 的 acquisition、validation 和 clean test 规模；
- 主要 baseline；
- 该领域覆盖的独特 self-evolution failure mode。

Clean-v2 规模以 `configs/experiments/clean-v2.yaml` 为准；Core-1 noise screen 的规模单独标为 pilot scale。两者不得在没有标签的情况下合并成同一组规模。

### 3. Baseline 方法与状态分层

Baseline 分为三层：

- **当前 reference baseline：** SkillOpt、SkillAdaptor、SkillLearnBench self-feedback，以及用于 N4 的 SkillLearnBench teacher-feedback。
- **计划接入的 comparison baseline：** Trace2Skill、SkillGrad、EvoSkill、RethinkSkill、Skills-Coach、SkillFlow 和 FederatedSkill。每项说明原生领域、更新机制及当前 inactive/adaptation 状态。
- **不可执行的研究参考：** CoEvoSkills。在官方代码可运行或出现明确标注的独立 reimplementation 前，保持 paper-only 状态。

该部分必须区分 native reproduction、compatibility patch 和 unified-harness adaptation，不能暗示 inactive registry 项已经完成正式实验。

### 4. N1–N4 噪声模型

按噪声进入 learning pipeline 的位置定义四个阶段：

```text
task instance -> environment interaction -> stored trajectory -> update feedback
      N1                  N2                     N3                 N4
```

- N1 在第一次 action 前改变 task-side context。
- N2 改变执行期间可见的 evidence 或 observation source。
- N3 在 execution/reward 之后、reflection 之前改变保存的 trajectory。
- N4 在 skill update 之前改变 reflection、critique 或 fault attribution。

文档应明确：N1/N2 是静态 paired artifacts；N3/N4 是会生成 replay pack 的确定性 runtime mutation；四个阶段是相互独立的实验 arm，而不是默认进行笛卡尔组合。当前所有 Core-1 operator 均采用一次 L2 mutation，并在不适用时 fail closed、记录 `applicable=false`。

### 5. 四领域加噪矩阵

加入一张从 active Core-1 YAML 逐项生成的 4×4 表格。每个单元格同时写出具体 operator 和必须保持不变的 protected information。该表是协作者实现和审查 noise adapter 时的核心参考。

### 6. 实验流程与晋级门槛

展示以下阶段依赖：

```text
baseline bootstrap 与 identity verification
-> clean engineering readiness
-> clean efficacy readiness
-> immutable clean release
-> 独立验证 N1-N4
-> benchmark freeze
-> comparison baseline 与 RGSE
```

严格记录 clean-v2 单元判定规则：

- `engineering_ready`：三个固定 method seed 中至少两个产生通过 baseline 原生 validation gate 的更新；artifact 语义发生变化；clean performance 不下降；且没有使结果失效的系统性执行错误。
- `efficacy_ready`：首先满足 `engineering_ready`，并且三个固定 seed 中至少两个获得严格为正的 clean gain。
- 所有必需 Core-1 单元达到 `efficacy_ready` 后，才允许开始 N1–N4 正式验证。

Noise operator 的后续晋级依次要求 validity、seed calibration、applicability、真实 clean update、在 untouched clean test 上可观察的 clean-minus-noisy effect，以及独立重复。Null、opposite、blocked、inapplicable 等结果必须按照协议留在分母中或以对应 typed status 报告。

### 7. 当前状态与已知限制

提供带日期的状态块，并链接到详细报告。状态必须分别描述：

- execution/interface readiness；
- 是否能够接受 update；
- 是否得到 positive clean efficacy；
- 是否得到 stable noise efficacy。

不能因为四个单元都能启动进程，就声称它们都已满足 readiness。实时运行中的易变数字应进入带日期的报告或冻结 release summary，不应写入长期有效的 benchmark 定义。

### 8. 协作者工作计划

按依赖关系组织任务，而不是按仓库目录罗列：

1. 完成并冻结 clean-v2 证据；
2. 只修复由 typed interface failure 判定为无效的单元，并完整重跑受影响单元；
3. 达到规定的 clean engineering 和 efficacy readiness；
4. 先逐领域验证 N1，再独立验证 N2–N4；
5. 冻结通过晋级的 operator、manifest、hash、replay pack 和报告；
6. 按 native-domain 优先级激活 comparison baseline；
7. 只在 benchmark freeze 后实现和评测 RGSE；
8. 运行最终多 seed、paired、完整计费实验并发布 benchmark card。

每个阶段都要说明验收证据，以及哪些修改会使旧结果失效。清单还要明确禁止以下捷径：按已观察到的 final-test outcome 选择样本、查看 test 后重新调噪声、未披露地修改 baseline 核心算法、删除 zero-update seed、提交 secret 或原始大规模运行目录。

### 9. 可复现性与仓库索引

链接到 registry、baseline patch series、clean manifest、Core-1 config、runtime evidence interface、compact release、result contract 和 unified CLI。说明 external baseline clone、raw dataset、完整 trajectory、逐调用 token ledger 和 secret 均为本地/gitignored 产物。

### 10. 候选扩展

按证据状态列出 inactive benchmark 和方法，明确它们是未来候选，而非 Core-1 blocker。候选 benchmark 的激活条件为：具有可靠 verifier、冻结 split、至少两个可信方法交集或明确标记的 adapted baseline，并使用与 Core-1 相同的 clean/noise qualification contract。

## 写作与维护规则

- 使用中文写作，保留正式 benchmark、method、schema 和 metric 的英文名称。
- 优先使用表格和短定义，减少历史流水账。
- 使用相对仓库链接，确保 GitHub 可以正确渲染。
- 使用 active、inactive、candidate、blocked、diagnostic、paper-only 等明确状态词。
- 不得把研究假设、pilot signal 或单一 family 结果描述成稳定 benchmark 结论。
- 详细数值结果指向带日期的报告；只有项目范围、判定门槛或 frozen release 状态发生变化时才更新路线图。
- 不包含 credential、本机绝对路径，也不把仅存在于 gitignored output 中的文件作为公开结论的唯一证据。

## 验证要求

提交最终文档前必须：

1. 根据 registry 或可执行 YAML 核对每个 active benchmark、method、repository revision、operator 和样本规模；
2. 确认 16 个 Core-1 operator 单元均且仅出现一次；
3. 检查当前范围与候选扩展是否存在矛盾；
4. 扫描占位符和缺少证据的完成性表述；
5. 验证全部相对仓库链接；
6. 运行当前分支规则要求的文档/registry 测试及仓库测试。

## 完成标准

当协作者能够通过该文档识别当前四领域矩阵、理解每个 N1–N4 注入位置、区分当前与计划 baseline、遵循阶段门槛、选择下一个未阻塞任务，并能找到每项可执行声明对应的机器可读来源时，文档视为完成。
