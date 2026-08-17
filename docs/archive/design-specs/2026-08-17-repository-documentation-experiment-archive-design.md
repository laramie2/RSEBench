# 仓库文档、实验历史与协作进度整理设计

> 日期：2026-08-17（UTC）
>
> 状态：已完成方案讨论，等待用户复核书面设计后实施
>
> 范围：文档分类、历史实验索引、本地产物清理、旧 worktree 收敛、四位成员 N1–N4 进度汇报
>
> 非目标：不改变 validation-v1 的 DatasetRelease、MethodRelease、4×4 matrix、noise operator 语义或实验结果

## 1. 目标与原则

本次整理要让协作者能够从少量当前文档进入项目、按项目阶段查找历史实验，并明确区分可执行真源、历史证据和可删除中间产物。整理完成后应满足：

1. 当前文档按作用分类，过期文档进入独立归档；
2. `project-onboarding.md`、`project-roadmap.md`、根 `README.md` 与 validation-v1 实际状态一致；
3. 历史实验按项目阶段建立统一索引，保留结论、配置、manifest、结果和 token/timing 入口；
4. 四位成员分别维护 N1、N2、N3、N4 的稳定进度页，避免多人频繁修改同一文件；
5. validation-v1 已冻结的内容 hash、历史证据引用和可重放路径不因整理而失效；
6. 只删除可重建或已确认重复的内容，付费运行证据默认保留；
7. 每一批迁移都可独立验证和回滚。

采用“保守混合整理”：文档实际迁移；实验通过阶段索引统一组织，只移动没有被冻结 release、配置或测试引用的产物；缓存与明确重复项可删除。旧 manifest、旧脚本和旧配置不在本轮进行激进的全量重构。

## 2. 当前状态与风险

只读盘点得到以下事实：

- `docs/` 有 52 个文件，其中 18 份报告、17 份实施计划、13 份设计文档，总体约 768 KB；
- 本地目录约 14 GB，主要由 `methods/external/`、`data/`、`outputs/`、虚拟环境和旧 worktree 构成；
- `docs/project-onboarding.md` 仍把项目描述为 M2 clean 数据筛选阶段，而且当前未被 Git 跟踪；
- `docs/project-roadmap.md` 已包含 validation-v1，但仍保留与当前冻结状态冲突的旧阶段说明；
- 根 `README.md` 与 `benchmark/core1/README.md` 仍把 SkillLearnBench 列为当前第四个主领域；
- validation-v1 release 直接引用 `benchmark/validation/clean_qualification_v2/`、`benchmark/validation/skillflow_clean_qualification_v1/` 和若干 SkillFlow clean evidence 路径，不能直接移动；
- 两个旧分支都已合入 `main`，但旧 worktree 中仍有未迁移的历史结果和一份未跟踪计划，不能直接删除；
- 主工作树缺少若干报告引用的历史结果，其中 expanded-N1 aggregate 和部分 Core-1 结果仍存在于 `.worktrees/rsebench-pilot/outputs/`。

因此本次整理必须先完成证据可达性审计，再处理 worktree 和输出目录。

## 3. 文档信息架构

目标目录如下：

```text
docs/
├── README.md
├── project-onboarding.md
├── project-roadmap.md
├── architecture/
│   ├── validation-v1-architecture.md
│   └── repository-layout.md
├── protocols/
│   ├── dataset-and-method-release.md
│   ├── noise-stage-interface.md
│   └── token-timing-and-result-contract.md
├── operations/
│   ├── validation-runbook.md
│   └── collaborator-workflow.md
├── progress/
│   ├── README.md
│   ├── n1-task-context.md
│   ├── n2-environment-evidence.md
│   ├── n3-stored-trajectory.md
│   ├── n4-update-feedback.md
│   ├── templates/
│   │   └── stage-progress-template.md
│   └── archive/
├── reports/
│   └── current/
│       ├── current-project-status.md
│       └── 2026-08-17-validation-v1-freeze.md
└── archive/
    ├── README.md
    ├── design-specs/
    ├── implementation-plans/
    ├── status-snapshots/
    └── experiment-history/
        ├── README.md
        ├── registry.yaml
        ├── 00-foundation-and-audits/
        ├── 01-api-pilot-and-initial-noise/
        ├── 02-expanded-n1/
        ├── 03-clean-qualification-and-repairs/
        ├── 04-stable-split-and-skilllearn-screening/
        ├── 05-skillflow-screening/
        └── 06-validation-v1-freeze/
```

当前文档使用稳定、无日期的职责型文件名；历史文档保留 `YYYY-MM-DD-` 前缀，使同一类别内自然按时间排序。`docs/README.md` 是文档总入口，`docs/archive/README.md` 解释归档规则和历史阶段。

## 4. 当前文档处理

### 4.1 项目入口

`project-onboarding.md` 将被纳入 Git，并更新为：

- validation-v1 四个 DatasetRelease 已冻结；
- 当前主领域为 Spreadsheet、OfficeQA、WebShop、SkillFlow，SkillLearn 仅保留 diagnostic history；
- 四个 active MethodRelease profile 与 4×4 共 16 个 noisy cell；
- 当前阶段是 N1–N4 operator 和 `CELL_RUNNERS` 实现，而不是继续筛选 clean 数据；
- 当前 clean evidence 的强弱边界，避免将机制验证 release 描述成四领域稳定正向 efficacy；
- 协作者入口、进度汇报入口和 provider-cost 安全要求。

`project-roadmap.md` 将统一为 M3，并明确：

- M2 已完成的是 validation-v1 机制验证输入冻结；
- M3 的完成条件是 operator、保护字段、runner 注册、provider-free preflight 和小规模加噪验证；
- N1–N4 正式结果尚未产生；
- 旧 clean qualification 与 SkillLearn 结论只作为历史证据；
- 当前架构、运行手册、进度页和归档报告的新链接。

根 `README.md` 将提供最短的项目入口、当前四领域、安装、preflight 和文档导航。`benchmark/core1/README.md` 保持原路径，但加上 legacy/diagnostic 标识并指向 validation-v1，避免旧复现入口被误认为当前正式矩阵。

### 4.2 架构、协议与运行文档

- 2026-08-17 validation-v1 设计转为 `architecture/validation-v1-architecture.md`；
- 当前代码布局和目录所有权写入 `architecture/repository-layout.md`；
- DatasetRelease/MethodRelease 身份规则整理为独立协议；
- N1/N2 静态数据接口与 N3/N4 runtime evidence 接口整理为统一 noise-stage 协议；
- token、调用、UTC 时间和结果文件约束整理为结果合同；
- 4×4 preflight、run、status、aggregate 命令集中到 validation runbook；
- Git 分支、baseline 串行/跨 benchmark 并行和 stage 目录所有权集中到 collaborator workflow。

已完成的设计、实施计划和被后续状态替代的报告进入 archive，不再与当前操作文档混排。

## 5. 四位成员进度汇报设计

`docs/progress/` 是当前协作状态的唯一人工汇报入口，不取代 machine-readable matrix、run status 或 Git commit。

### 5.1 文件所有权

| 文件 | 默认维护者 | 范围 |
|---|---|---|
| `n1-task-context.md` | member-1 | N1 在四个 benchmark 上的设计、实现和验证 |
| `n2-environment-evidence.md` | member-2 | N2 在四个 benchmark 上的设计、实现和验证 |
| `n3-stored-trajectory.md` | member-3 | N3 runtime evidence 注入与方法适配 |
| `n4-update-feedback.md` | member-4 | N4 feedback/update boundary 注入与方法适配 |
| `README.md` | 项目协调者 | 四阶段摘要、跨 stage 阻塞和近期里程碑 |

成员只常规修改自己的 stage 文件，避免四人同时编辑总览页产生冲突。协调者在合并 stage 更新后刷新 `README.md`。实际姓名确定后只更新 owner 字段，不修改文件路径。

### 5.2 Stage 进度页固定结构

每个 stage 文件包含：

1. owner、状态、最后更新时间（UTC）、工作分支和最新 commit；
2. stage 定义、污染边界和 protected fields；
3. 四 benchmark 进度表：operator ID、实现目录、单元测试、静态审计、preflight、runner 注册、是否可付费运行、结果入口；
4. 本周期完成内容；
5. 当前阻塞及需要谁协助；
6. 接下来最多三项工作；
7. 已作出的设计决定和仍需协调者确认的问题；
8. provider 调用、token、运行时长和结果目录；
9. handoff 信息，保证其他成员可以继续工作。

状态枚举固定为：`not_started`、`designing`、`implementing`、`preflight_ready`、`running`、`validated`、`blocked`。不能使用模糊的百分比代替具体 gate。

四 benchmark 进度表至少包含：

| Benchmark | Operator | Unit tests | Protected-field audit | Preflight | Runner | Paid run | Result |
|---|---|---|---|---|---|---|---|
| Spreadsheet | 状态 | 状态 | 状态 | 状态 | 状态 | 状态 | 链接 |
| OfficeQA | 状态 | 状态 | 状态 | 状态 | 状态 | 状态 | 链接 |
| WebShop | 状态 | 状态 | 状态 | 状态 | 状态 | 状态 | 链接 |
| SkillFlow | 状态 | 状态 | 状态 | 状态 | 状态 | 状态 | 链接 |

### 5.3 更新节奏与归档

- stage 状态变化、出现 blocker、启动付费运行或得到结果时必须更新；
- 连续开发期间至少每个工作日结束前更新一次；
- 文档只记录摘要并链接 commit、issue、matrix cell 和输出，不粘贴大段原始日志；
- 每完成一个共同里程碑，将四份 stage 页与总览复制为一个带日期的只读 snapshot，放入 `docs/progress/archive/YYYY-MM-DD-<milestone>/`；
- 当前页始终使用稳定路径，协作者无需追踪最新日期文件；
- blocked 状态必须说明阻塞条件、影响范围、已尝试措施和解除条件。

## 6. 历史实验归档

历史实验按项目阶段建立人类可读时间线和 `registry.yaml`。每条记录至少包含：

```yaml
phase: 03-clean-qualification-and-repairs
experiment_id: clean-v2-20260814
date: 2026-08-14
purpose: clean baseline qualification
benchmarks: [spreadsheetbench_verified, officeqa_full, webshop, skilllearnbench]
baselines: [skillopt, skilladaptor, skilllearn_self_feedback]
status: completed
conclusion: "12/12 cells completed; execution loops passed and clean efficacy remained mixed."
config: configs/experiments/clean-v2.yaml
input_manifest: benchmark/validation/clean_qualification_v2/
output_root: outputs/runs/clean-v2-20260814
canonical_report: docs/archive/experiment-history/03-clean-qualification-and-repairs/2026-08-15-clean-v2-and-fixed-artifact-replay.md
token_and_timing_record: outputs/runs/clean-v2-20260814/events.jsonl
preservation_class: frozen-evidence
superseded_by: validation-v1
```

项目阶段定义为：

1. `00-foundation-and-audits`：下载、数据物化、benchmark/baseline 审计；
2. `01-api-pilot-and-initial-noise`：DeepSeek 适配、早期 pilot、初始 paired evolution；
3. `02-expanded-n1`：扩大样本 N1 验证；
4. `03-clean-qualification-and-repairs`：Clean-v1/v2、OfficeQA/WebShop 修复、fixed-artifact replay；
5. `04-stable-split-and-skilllearn-screening`：稳定样本候选和 SkillLearn diagnostic；
6. `05-skillflow-screening`：SkillFlow 迁移、family 筛选和 clean evidence；
7. `06-validation-v1-freeze`：DatasetRelease、MethodRelease、插件接口和 4×4 控制面冻结。

历史结果分为三类：

- `frozen-evidence`：release 或当前结论直接引用，原路径保留；
- `historical-evidence`：有审计价值但不进入当前实验，可按阶段迁移并生成 checksum；
- `rebuildable-intermediate`：缓存、重复 smoke、失败重试副本，可在验证后清理。

归档索引记录逻辑阶段，不要求所有原始结果都物理移动。任何被 release 或 replay locator 引用的路径以身份稳定性优先。

## 7. 代码、数据与中间产物清理

### 7.1 第一档：可重建内容

审批范围内可清理：

- `__pycache__`、`.pytest_cache`、`.ruff_cache`；
- `pytest-of-nvidia/`；
- `src/rsebench.egg-info/`；
- 空的 stale preflight 目录；
- 明确可重新生成的模型缓存与测试临时输出。

### 7.2 第二档：证据迁出后清理

- 两个已合并旧 worktree；
- 重复的 SkillFlow smoke/preflight；
- incomplete、重复失败和已经由完整重试替代的输出；
- 外部 baseline 内可重建的独立虚拟环境；
- 可由原始数据和 manifest 重新 materialize 的候选数据副本；
- 经 `rg`、import、测试和文档引用审计确认无使用者的旧脚本。

第二档逐项列出源路径、目标或删除理由、大小、checksum、依赖扫描结果和恢复方法。没有证据证明可删除的项目默认保留。

### 7.3 本轮不移动或删除

- 四个 active benchmark 的冻结数据与 materialization；
- active baseline 源码、patch 和 release；
- validation-v1 引用的历史 manifest 和 clean evidence；
- `benchmark/core1`、旧 configs/scripts 等仍参与历史复现或测试的 tracked 资产；
- 候选方法的 Git 源码，除非另行确认可以重新 bootstrap。

## 8. 迁移顺序与安全措施

实施拆为独立提交：

1. 生成整理前 inventory、Git 状态、路径引用和 checksum；
2. 将两份未跟踪文档纳入保护清单，迁出旧 worktree 中主目录缺失的历史结果；
3. 创建文档索引、current 分类、archive 分类和 progress 目录；
4. 使用 `git mv` 迁移文档并修复所有相对链接；
5. 更新 onboarding、roadmap、根 README、Core-1 legacy 说明；
6. 创建历史实验 README 与 registry；
7. 迁移未被 identity/replay 引用的 historical-evidence；
8. 清理第一档内容；
9. 输出第二档候选清单并执行已批准条目；
10. 运行完整验证并提交最终状态。

移动前先复制或归档独有证据，确认 checksum 一致后才删除原位置。worktree 使用 `git worktree remove` 正常注销，不直接递归删除目录。任何路径依赖不明确时停止该项迁移，但不阻塞其余安全步骤。

## 9. 验证与完成标准

整理完成必须满足：

- 四个 DatasetRelease content hash 不变；
- 四个 active MethodRelease identity 不变；
- `configs/validation/validation-v1.yaml` 的 16 个 cell 身份不变；
- provider-free validation preflight 通过，provider 调用为 0；
- 当前文档内部链接、相对代码链接和历史结果 locator 全部可解析，明确标注的外部冷存储除外；
- progress 总览和四份 stage 页结构完整、状态一致；
- 全量测试不新增失败；
- `git diff --check` 通过；
- 被保留和迁移的证据 checksum 与整理前一致；
- `git status` 只包含本次批准的更改；
- 清理报告记录实际删除路径、回收空间和恢复方式。

## 10. 审批边界

本设计默认批准：文档迁移与更新、实验阶段索引、progress 目录、第一档安全清理、证据迁出后移除两个已合并 worktree。

本设计不默认批准：压缩或删除历史付费运行原始证据、删除候选 baseline Git 源码、删除候选 benchmark 原始数据、改变 validation-v1 身份路径。此类操作需要单独列项确认。
